# Copyright (c) 2022, Frappe and contributors
# For license information, please see license.txt

from datetime import datetime

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, get_time, getdate, nowdate, nowtime

from lms.lms.utils import (
	convert_from_system_timezone,
	format_timezone,
	get_evaluation_display_timezone,
	get_evaluator,
)


class CourseEvaluator(Document):
	def validate(self):
		self.validate_evaluator_role()
		self.validate_time_slots()
		self.validate_unavailability()

	def on_trash(self):
		# Direct row delete, not User.remove_roles: see validate_evaluator_role.
		frappe.db.delete("Has Role", {"parent": self.evaluator, "role": "Batch Evaluator"})
		frappe.clear_cache(user=self.evaluator)

	def validate_evaluator_role(self):
		"""Being a Course Evaluator *is* holding the Batch Evaluator role.

		Written as a Has Role row rather than `User.add_roles`, which saves the
		whole User document: whenever the session user cannot write User docs
		(every portal Moderator, since LMS only grants them list access), the save
		is dropped and the role silently never lands, leaving an evaluator who
		cannot open their own schedule. lms.lms.api.save_evaluator_role writes
		the row directly for the same reason.
		"""
		if frappe.db.exists("Has Role", {"parent": self.evaluator, "role": "Batch Evaluator"}):
			return

		role = frappe.new_doc("Has Role")
		role.update(
			{
				"parent": self.evaluator,
				"parenttype": "User",
				"parentfield": "roles",
				"role": "Batch Evaluator",
			}
		)
		role.insert(ignore_permissions=True)
		frappe.clear_cache(user=self.evaluator)

	def validate_unavailability(self):
		if (
			self.unavailable_from
			and self.unavailable_to
			and getdate(self.unavailable_from) >= getdate(self.unavailable_to)
		):
			frappe.throw(_("Unavailable From Date cannot be greater than Unavailable To Date"))

	def validate_time_slots(self):
		for schedule in self.schedule:
			if get_time(schedule.start_time) >= get_time(schedule.end_time):
				frappe.throw(_("Start Time cannot be greater than End Time"))

			self.validate_overlaps(schedule)

	def validate_overlaps(self, schedule):
		same_day_slots = list(
			filter(lambda x: x.day == schedule.day and x.name != schedule.name, self.schedule)
		)
		overlap = False

		for slot in same_day_slots:
			if get_time(schedule.start_time) <= get_time(slot.start_time) < get_time(schedule.end_time):
				overlap = True
			if get_time(schedule.start_time) < get_time(slot.end_time) <= get_time(schedule.end_time):
				overlap = True
			if get_time(slot.start_time) < get_time(schedule.start_time) and get_time(
				schedule.end_time
			) < get_time(slot.end_time):
				overlap = True

			if overlap:
				frappe.throw(_("Slot Times are overlapping for some schedules."))


@frappe.whitelist()
def get_schedule(course: str, batch: str = None):
	evaluator = get_evaluator(course, batch)
	start_date = nowdate()
	end_date = get_schedule_range_end_date(start_date, batch)
	all_slots = get_all_slots(evaluator, start_date, end_date)
	booked_slots = get_booked_slots(evaluator, start_date, end_date)
	available = remove_booked_slots(all_slots, booked_slots)
	return group_slots_by_display_date(available, get_evaluation_display_timezone(course, batch))


def get_all_slots(evaluator, start_date, end_date):
	schedule = get_evaluator_schedule(evaluator)
	unavailable_dates = get_unavailable_dates(evaluator)
	all_slots = []
	current_date = getdate(start_date)
	end_date = getdate(end_date)

	while current_date <= end_date:
		if current_date in unavailable_dates:
			current_date = add_days(current_date, 1)
			continue
		day_of_week = current_date.strftime("%A")
		slots_for_day = [x for x in schedule if x.day == day_of_week]
		for slot in slots_for_day:
			if slot_has_started(current_date, slot.start_time):
				continue
			all_slots.append(
				frappe._dict(
					{
						"day": day_of_week,
						"date": current_date,
						"start_time": slot.start_time,
						"end_time": slot.end_time,
					}
				)
			)
		current_date = add_days(current_date, 1)
	return all_slots


def slot_has_started(date, start_time) -> bool:
	"""Both clocks are system time, and the strict `<` is the one
	LMSCertificateRequest.validate_if_existing_requests books against, so a slot
	starting exactly now still counts. A picker that offers what the validator
	rejects is what put "You cannot schedule evaluations for past slots." in
	front of a learner who picked the first slot shown. Named apart from
	lms.lms.utils.has_started_today, which asks the same question of a batch.
	"""
	return getdate(date) == getdate() and get_time(start_time) < get_time(nowtime())


def get_evaluator_schedule(evaluator):
	return frappe.get_all(
		"Evaluator Schedule",
		filters={
			"parent": evaluator,
		},
		fields=["day", "start_time", "end_time"],
		order_by="start_time",
	)


def get_booked_slots(evaluator, start_date, end_date):
	date = ["between", [start_date, end_date]]
	return frappe.get_all(
		"LMS Certificate Request",
		filters={
			"evaluator": evaluator,
			"date": date,
			"status": ["!=", "Cancelled"],
		},
		fields=["start_time", "day", "date"],
	)


def remove_booked_slots(all_slots, booked_slots):
	slots_to_remove = []
	for slot in all_slots:
		for booked in booked_slots:
			if slot.date == booked.date and slot.start_time == booked.start_time:
				slots_to_remove.append(slot)

	for slot in slots_to_remove:
		all_slots.remove(slot)

	return all_slots


def group_slots_by_display_date(all_slots, timezone):
	"""Group by the date each slot falls on *in the display timezone*.

	Grouping has to happen after conversion, not before: an evaluator's Monday
	09:00 in Asia/Kolkata is Sunday 20:30 in America/Los_Angeles, so a Monday
	schedule row legitimately produces Sunday slots for a US-West batch.

	Each slot carries both clocks. `date`/`start_time`/`end_time` are the system
	values the booking is submitted with. Everything downstream (`validate_slot`,
	past-slot rejection, completion, the calendar event) reads system time.
	`display_*` is what the learner sees. One display group can hold slots from
	two different system dates, so the system date lives on the slot, not the group.
	"""
	groups = {}
	for slot in all_slots:
		display_date, display_start = convert_from_system_timezone(slot.date, slot.start_time, timezone)
		display_end_date, display_end = convert_from_system_timezone(slot.date, slot.end_time, timezone)
		date_str = display_date.strftime("%Y-%m-%d")

		if date_str not in groups:
			groups[date_str] = {
				"display_date": date_str,
				"display_day": display_date.strftime("%A"),
				"display_timezone": timezone,
				"display_timezone_label": format_timezone(
					timezone, datetime.combine(display_date, display_start)
				),
				"slots": [],
			}

		groups[date_str]["slots"].append(
			{
				"date": slot.date.strftime("%Y-%m-%d"),
				"day": slot.day,
				"start_time": slot.start_time,
				"end_time": slot.end_time,
				"display_start_time": display_start.strftime("%H:%M:%S"),
				"display_end_time": display_end.strftime("%H:%M:%S"),
				# A slot that sits inside one system day can straddle midnight once
				# converted: 17:00-19:00 Asia/Kolkata is 23:30-01:30 in
				# Pacific/Auckland. Without this the picker would render
				# "23:30 - 01:30" under one date and say nothing about which day the
				# slot ends on.
				"display_end_date": display_end_date.strftime("%Y-%m-%d"),
			}
		)

	for group in groups.values():
		group["slots"].sort(key=lambda slot: slot["display_start_time"])

	return [groups[date_str] for date_str in sorted(groups)]


def get_evaluator_availability(evaluator):
	return frappe.db.get_value(
		"Course Evaluator", evaluator, ["unavailable_from", "unavailable_to"], as_dict=1
	)


def get_unavailable_dates(evaluator):
	availability = get_evaluator_availability(evaluator)
	unavailable_dates = []
	if availability.unavailable_from and availability.unavailable_to:
		current_date = getdate(availability.unavailable_from)
		end_date = getdate(availability.unavailable_to)

		while current_date <= end_date:
			unavailable_dates.append(current_date)
			current_date = add_days(current_date, 1)
	return unavailable_dates


def get_schedule_range_end_date(start_date, batch=None):
	end_date = add_days(start_date, 60)
	if batch:
		batch_end_date = frappe.db.get_value("LMS Batch", batch, "evaluation_end_date")
		if batch_end_date and batch_end_date < getdate(end_date):
			end_date = getdate(batch_end_date)

	return end_date


import json
import frappe
from frappe import _
from frappe.utils import cint, getdate


DOCTYPE_EVALUATOR = "Course Evaluator"


def get_request_data():
    """Read JSON or form parameters from the current request."""

    data = {}

    if frappe.request:
        try:
            body = frappe.request.get_json(silent=True)
            if isinstance(body, dict):
                data.update(body)
        except Exception:
            pass

    # Form/query parameters take precedence when supplied.
    if frappe.form_dict:
        for key, value in frappe.form_dict.items():
            if key not in ("cmd", "doctype"):
                data[key] = value

    return data


def parse_schedule(schedule):
    """Convert the schedule payload into a list of child-table rows."""

    if schedule is None or schedule == "":
        return None

    if isinstance(schedule, str):
        try:
            schedule = json.loads(schedule)
        except json.JSONDecodeError:
            frappe.throw(_("Schedule must be valid JSON."))

    if not isinstance(schedule, list):
        frappe.throw(_("Schedule must be a JSON array."))

    for row in schedule:
        if not isinstance(row, dict):
            frappe.throw(_("Each schedule entry must be a JSON object."))

        if "name" in row or "parent" in row or "parenttype" in row:
            frappe.throw(
                _("Do not provide child-table system fields in schedule.")
            )

    return schedule


def validate_evaluator_data(data, creating=False):
    """Validate the evaluator, dates, and schedule."""

    if creating and not data.get("evaluator"):
        frappe.throw(_("Evaluator is required."))

    evaluator = data.get("evaluator")

    if evaluator and not frappe.db.exists("User", evaluator):
        frappe.throw(
            _("User {0} does not exist.").format(evaluator)
        )

    start = data.get("unavailable_from")
    end = data.get("unavailable_to")

    if start and end and getdate(start) > getdate(end):
        frappe.throw(
            _("Unavailable From cannot be later than Unavailable To.")
        )


def evaluator_response(doc):
    """Format the evaluator document for API responses."""

    return {
        "name": doc.name,
        "evaluator": doc.evaluator,
        "full_name": doc.full_name,
        "username": doc.username,
        "user_image": doc.user_image,
        "unavailable_from": doc.unavailable_from,
        "unavailable_to": doc.unavailable_to,
        "schedule": [
            row.as_dict()
            for row in doc.schedule
        ],
        "owner": doc.owner,
        "creation": doc.creation,
        "modified": doc.modified,
    }


@frappe.whitelist(methods=["POST"])
def create_course_evaluator(
    evaluator=None,
    schedule=None,
    unavailable_from=None,
    unavailable_to=None,
    **kwargs
):
    """Create a Course Evaluator."""

    data = get_request_data()

    if evaluator is not None:
        data["evaluator"] = evaluator

    if schedule is not None:
        data["schedule"] = schedule

    if unavailable_from is not None:
        data["unavailable_from"] = unavailable_from

    if unavailable_to is not None:
        data["unavailable_to"] = unavailable_to

    data.update(kwargs)

    schedule_rows = parse_schedule(data.get("schedule"))

    validate_evaluator_data(data, creating=True)

    user = frappe.db.get_value(
        "User",
        data["evaluator"],
        ["full_name", "username", "user_image"],
        as_dict=True,
    )

    doc = frappe.get_doc({
        "doctype": DOCTYPE_EVALUATOR,
        "evaluator": data["evaluator"],
        "full_name": user.full_name,
        "username": user.username,
        "user_image": user.user_image,
        "unavailable_from": data.get("unavailable_from"),
        "unavailable_to": data.get("unavailable_to"),
    })

    if schedule_rows is not None:
        doc.set("schedule", schedule_rows)

    doc.insert()

    return {
        "success": True,
        "message": "Course evaluator created successfully.",
        "data": evaluator_response(doc),
    }


@frappe.whitelist(methods=["GET"])
def get_course_evaluator(name):
    """Get one evaluator by document name."""

    if not frappe.db.exists(DOCTYPE_EVALUATOR, name):
        frappe.throw(
            _("Course Evaluator {0} does not exist.").format(name),
            frappe.DoesNotExistError,
        )

    doc = frappe.get_doc(DOCTYPE_EVALUATOR, name)
    doc.check_permission("read")

    return {
        "success": True,
        "data": evaluator_response(doc),
    }


@frappe.whitelist(methods=["GET"])
def get_course_evaluator_list(
    evaluator=None,
    txt=None,
    limit_start=0,
    limit_page_length=20,
):
    """Get a permission-filtered evaluator list."""

    filters = {}

    if evaluator:
        filters["evaluator"] = evaluator

    or_filters = None

    if txt:
        or_filters = [
            ["Course Evaluator", "evaluator", "like", f"%{txt}%"],
            ["Course Evaluator", "full_name", "like", f"%{txt}%"],
            ["Course Evaluator", "username", "like", f"%{txt}%"],
        ]

    rows = frappe.get_list(
        DOCTYPE_EVALUATOR,
        filters=filters,
        or_filters=or_filters,
        fields=[
            "name",
            "evaluator",
            "full_name",
            "username",
            "user_image",
            "unavailable_from",
            "unavailable_to",
            "owner",
            "creation",
            "modified",
        ],
        order_by="modified desc",
        start=max(cint(limit_start), 0),
        page_length=min(max(cint(limit_page_length), 1), 100),
    )

    return {
        "success": True,
        "count": len(rows),
        "data": rows,
    }


@frappe.whitelist(methods=["PUT", "PATCH", "POST"])
def update_course_evaluator(
    name,
    evaluator=None,
    schedule=None,
    unavailable_from=None,
    unavailable_to=None,
    **kwargs
):
    """Update a Course Evaluator and its schedule."""

    if not frappe.db.exists(DOCTYPE_EVALUATOR, name):
        frappe.throw(
            _("Course Evaluator {0} does not exist.").format(name),
            frappe.DoesNotExistError,
        )

    doc = frappe.get_doc(DOCTYPE_EVALUATOR, name)
    doc.check_permission("write")

    data = get_request_data()

    if evaluator is not None:
        data["evaluator"] = evaluator

    if schedule is not None:
        data["schedule"] = schedule

    if unavailable_from is not None:
        data["unavailable_from"] = unavailable_from

    if unavailable_to is not None:
        data["unavailable_to"] = unavailable_to

    data.update(kwargs)

    # Evaluator is also the document's naming field.
    # Changing it would change the identity of the record.
    if data.get("evaluator") and data["evaluator"] != doc.evaluator:
        frappe.throw(
            _("Changing the evaluator is not supported by this API.")
        )

    validate_evaluator_data({
        "evaluator": doc.evaluator,
        "unavailable_from": data.get(
            "unavailable_from", doc.unavailable_from
        ),
        "unavailable_to": data.get(
            "unavailable_to", doc.unavailable_to
        ),
    })

    if "unavailable_from" in data:
        doc.unavailable_from = data["unavailable_from"] or None

    if "unavailable_to" in data:
        doc.unavailable_to = data["unavailable_to"] or None

    if "schedule" in data:
        schedule_rows = parse_schedule(data["schedule"])

        if schedule_rows is not None:
            doc.set("schedule", schedule_rows)

    # Refresh profile fields from the linked User.
    user = frappe.db.get_value(
        "User",
        doc.evaluator,
        ["full_name", "username", "user_image"],
        as_dict=True,
    )

    if user:
        doc.full_name = user.full_name
        doc.username = user.username
        doc.user_image = user.user_image

    doc.save()

    return {
        "success": True,
        "message": "Course evaluator updated successfully.",
        "data": evaluator_response(doc),
    }


@frappe.whitelist(methods=["DELETE", "POST"])
def delete_course_evaluator(name):
    """Delete a Course Evaluator."""

    if not frappe.db.exists(DOCTYPE_EVALUATOR, name):
        frappe.throw(
            _("Course Evaluator {0} does not exist.").format(name),
            frappe.DoesNotExistError,
        )

    doc = frappe.get_doc(DOCTYPE_EVALUATOR, name)
    doc.check_permission("delete")

    doc.delete()

    return {
        "success": True,
        "message": "Course evaluator deleted successfully.",
        "name": name,
    }