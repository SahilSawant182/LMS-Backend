# Copyright (c) 2021, FOSS United and contributors
# For license information, please see license.txt

from contextlib import contextmanager

import frappe
from frappe import _
from frappe.desk.doctype.notification_log.notification_log import make_notification_logs
from frappe.model.document import Document
from frappe.utils import ceil, nowdate

IDENTITY_FIELDS = ("course", "member", "enrollment_from_batch")


class LMSEnrollment(Document):
	def before_insert(self):
		self.validate_duplicate_enrollment()
		self.validate_course_enrollment_eligibility()
		self.validate_owner()

	def validate(self):
		validate_identity_unchanged(self, IDENTITY_FIELDS)
		self.enforce_server_managed_fields()

	def enforce_server_managed_fields(self):
		"""Revert progress / purchased_certificate to their server-set values for non-staff."""
		from lms.lms.utils import PRIVILEGED_ROLES

		if PRIVILEGED_ROLES & set(frappe.get_roles()):
			return

		previous = None if self.is_new() else self.get_doc_before_save()
		defaults = {"progress": 0, "purchased_certificate": 0}
		for field, default in defaults.items():
			setattr(self, field, previous.get(field) if previous else default)

	def validate_owner(self):
		"""Makes the member as the owner of the document so that users can update their progress"""
		if self.owner != self.member:
			self.owner = self.member

	def after_insert(self):
		"""N1: Send enrollment confirmation email to the student.
		N2: Notify instructors of the new student enrollment."""
		self.send_enrollment_confirmation_to_student()
		self.notify_instructors_of_new_enrollment()

	def on_update(self):
		update_program_progress(self.member)
		self.notify_course_completion()
		self.notify_instructors_of_course_completion()

	def after_insert(self):
		if self.member_type == "Student":
			_update_course_enrollments(self.course, increment=True)

	def after_delete(self):
		if self.member_type == "Student":
			_update_course_enrollments(self.course, increment=False)

	def validate_duplicate_enrollment(self):
		# Lock the course row first: see the note in
		# lms_batch_enrollment.validate_duplicate_members. Two concurrent
		# enrolments in the same course both read "absent" without it.
		frappe.db.get_value("LMS Course", self.course, "name", for_update=True)

		existing_enrollment = frappe.db.exists(
			"LMS Enrollment",
			{
				"course": self.course,
				"member": self.member,
				"name": ["!=", self.name],
			},
		)

		if existing_enrollment and existing_enrollment != self.name:
			frappe.throw(_("Student is already enrolled in this course."))

	def validate_course_enrollment_eligibility(self):
		course_details = frappe.db.get_value(
			"LMS Course",
			self.course,
			["published", "disable_self_learning", "paid_course", "paid_certificate"],
			as_dict=True,
		)

		if course_details.disable_self_learning and not is_admin():
			frappe.throw(
				_(
					"You cannot enroll in this course as self-learning is disabled. Please contact the Administrator."
				)
			)

		if self.enrollment_from_batch:
			if not frappe.db.exists(
				"Batch Course", {"parent": self.enrollment_from_batch, "course": self.course}
			):
				frappe.throw(_("This batch is not associated with this course."))

			if frappe.db.exists(
				"LMS Batch Enrollment", {"batch": self.enrollment_from_batch, "member": self.member}
			):
				return

		if not course_details.published and not is_admin():
			frappe.throw(_("You cannot enroll in an unpublished course."))

		if course_details.paid_course and not is_admin():
			payment = frappe.db.exists(
				"LMS Payment",
				{
					"payment_for_document_type": "LMS Course",
					"payment_for_document": self.course,
					"member": self.member,
					"payment_received": True,
				},
			)

			if not payment:
				frappe.throw(_("You need to complete the payment for this course before enrolling."))


	# ─────────────────────────────────────────────────────────────────
	# Notification helpers (N1, N2, N5)
	# ─────────────────────────────────────────────────────────────────

	def send_enrollment_confirmation_to_student(self):
		"""N1 – Email the student a confirmation when they enroll in a free course.
		N4 – Email the student payment receipt + enrollment confirmation for paid course.
		Skipped for batch-linked enrollments (batch confirmation email handles those)."""
		if self.enrollment_from_batch:
			return

		paid_course = frappe.db.get_value("LMS Course", self.course, "paid_course")
		if paid_course or self.payment:
			self.send_paid_enrollment_confirmation_to_student()
			return

		outgoing_email_account = frappe.get_cached_value(
			"Email Account", {"default_outgoing": 1, "enable_outgoing": 1}, "name"
		)
		if not (outgoing_email_account or frappe.conf.get("mail_login")):
			return

		course_title = frappe.db.get_value("LMS Course", self.course, "title") or self.course
		student_name = frappe.db.get_value("User", self.member, "full_name") or self.member
		from lms.lms.utils import get_frontend_url
		app_name = "Stridenex-LMS"
		site_url = get_frontend_url()
		course_link = f"/course/{self.course}"

		subject = _("You are enrolled in {0}!").format(course_title)
		args = {
			"student_name": student_name,
			"course_title": course_title,
			"course_link": course_link,
			"enrollment_date": frappe.utils.format_date(nowdate(), "medium"),
			"site_url": site_url,
			"app_name": app_name,
		}

		try:
			frappe.sendmail(
				recipients=self.member,
				subject=subject,
				template="course_enrollment_confirmation",
				args=args,
				header=[subject, "green"],
				retry=3,
			)
		except Exception:
			frappe.log_error(
				frappe.get_traceback(), "LMS: Course enrollment confirmation email failed"
			)

	def send_paid_enrollment_confirmation_to_student(self):
		"""N4 – Email the student payment receipt + enrollment confirmation for a paid course."""
		outgoing_email_account = frappe.get_cached_value(
			"Email Account", {"default_outgoing": 1, "enable_outgoing": 1}, "name"
		)
		if not (outgoing_email_account or frappe.conf.get("mail_login")):
			return

		course_title = frappe.db.get_value("LMS Course", self.course, "title") or self.course
		student_name = frappe.db.get_value("User", self.member, "full_name") or self.member
		from lms.lms.utils import get_frontend_url
		app_name = "Stridenex-LMS"
		site_url = get_frontend_url()
		course_link = f"/course/{self.course}"

		payment_data = None
		if self.payment:
			payment_data = frappe.db.get_value(
				"LMS Payment",
				self.payment,
				["name", "amount", "currency", "payment_id", "creation"],
				as_dict=True,
			)
		if not payment_data:
			payment_data = frappe.db.get_value(
				"LMS Payment",
				{
					"member": self.member,
					"payment_for_document": self.course,
					"payment_for_document_type": "LMS Course",
					"payment_received": 1,
				},
				["name", "amount", "currency", "payment_id", "creation"],
				as_dict=True,
			)

		amount = payment_data.amount if payment_data and payment_data.amount else 0.0
		currency = (payment_data.currency if payment_data and payment_data.currency else "INR")
		payment_id = (payment_data.payment_id or payment_data.name) if payment_data else self.name
		payment_date = (
			frappe.utils.format_date(payment_data.creation, "medium")
			if payment_data and payment_data.creation
			else frappe.utils.format_date(nowdate(), "medium")
		)

		subject = _("Payment Confirmed: Enrolled in {0}").format(course_title)
		args = {
			"student_name": student_name,
			"course_title": course_title,
			"amount": amount,
			"currency": currency,
			"payment_id": payment_id,
			"payment_date": payment_date,
			"enrollment_date": frappe.utils.format_date(nowdate(), "medium"),
			"site_url": site_url,
			"course_link": course_link,
			"app_name": app_name,
		}

		try:
			frappe.sendmail(
				recipients=self.member,
				subject=subject,
				template="paid_course_enrollment_confirmation",
				args=args,
				header=[subject, "green"],
				retry=3,
			)
		except Exception:
			frappe.log_error(
				frappe.get_traceback(), "LMS: Paid course enrollment confirmation email failed"
			)

	def notify_instructors_of_new_enrollment(self):
		"""N2 – System notification to every instructor of the course when a student enrolls."""
		instructors = frappe.get_all(
			"Course Instructor",
			{"parent": self.course, "parenttype": "LMS Course"},
			pluck="instructor",
		)
		if not instructors:
			return

		Student = frappe.qb.DocType("User")
		student_name = (
			frappe.qb.from_(Student)
			.select(Student.full_name)
			.where(Student.name == self.member)
		).run(pluck=True)
		student_name = student_name[0] if student_name else self.member

		course_title = frappe.db.get_value("LMS Course", self.course, "title")
		from lms.lms.utils import get_lms_route
		link = get_lms_route(f"courses/{self.course}")

		notification = frappe._dict(
			{
				"subject": _("{0} enrolled in your course {1}").format(
					frappe.bold(student_name), frappe.bold(course_title)
				),
				"email_content": _(
					"{0} has just enrolled in your course '{1}'. Check the course dashboard for details."
				).format(student_name, course_title),
				"document_type": "LMS Enrollment",
				"document_name": self.name,
				"from_user": self.member,
				"type": "Alert",
				"link": link,
			}
		)
		try:
			make_notification_logs(notification, instructors)
		except Exception:
			frappe.log_error(
				frappe.get_traceback(), "LMS: Instructor enrollment notification failed"
			)

	def notify_course_completion(self):
		"""N5 – System notification to the student when they reach 100% course progress."""
		if not self.has_value_changed("progress"):
			return

		progress = frappe.utils.flt(self.progress)
		if progress < 100:
			return

		# Guard: don't fire again if it was already 100 before this update
		doc_before = self.get_doc_before_save()
		if doc_before and frappe.utils.flt(doc_before.get("progress")) >= 100:
			return

		course_title = frappe.db.get_value("LMS Course", self.course, "title")
		from lms.lms.utils import get_lms_route
		link = get_lms_route(f"courses/{self.course}")

		enable_certification = frappe.db.get_value("LMS Course", self.course, "enable_certification")
		if enable_certification:
			subject = _("🎉 You completed {0}! Your certificate is ready.").format(course_title)
			email_content = _(
				"Congratulations! You have completed 100% of {0}. "
				"You can now download your certificate of completion."
			).format(frappe.bold(course_title))
		else:
			subject = _("🎉 You completed {0}!").format(course_title)
			email_content = _(
				"Congratulations! You have successfully completed all lessons in {0}. "
				"Keep up the great learning!"
			).format(frappe.bold(course_title))

		notification = frappe._dict(
			{
				"subject": subject,
				"email_content": email_content,
				"document_type": "LMS Enrollment",
				"document_name": self.name,
				"from_user": frappe.session.user,
				"type": "Alert",
				"link": link,
			}
		)
		try:
			make_notification_logs(notification, [self.member])
		except Exception:
			frappe.log_error(
				frappe.get_traceback(), "LMS: Course completion notification failed"
			)

	def notify_instructors_of_course_completion(self):
		"""N33 – System notification to course instructors when a student completes 100%."""
		if not self.has_value_changed("progress"):
			return

		progress = frappe.utils.flt(self.progress)
		if progress < 100:
			return

		doc_before = self.get_doc_before_save()
		if doc_before and frappe.utils.flt(doc_before.get("progress")) >= 100:
			return  # was already 100 before

		instructors = frappe.get_all(
			"Course Instructor",
			{"parent": self.course, "parenttype": "LMS Course"},
			pluck="instructor",
		)
		if not instructors:
			return

		course_title = frappe.db.get_value("LMS Course", self.course, "title") or self.course
		student_name = frappe.db.get_value("User", self.member, "full_name") or self.member
		from lms.lms.utils import get_lms_route
		link = get_lms_route(f"courses/{self.course}")

		notification = frappe._dict(
			{
				"subject": _("🏅 {0} completed your course {1}!").format(
					frappe.bold(student_name), frappe.bold(course_title)
				),
				"email_content": _(
					"{0} has successfully completed 100% of your course '{1}'. "
					"Great teaching pays off!"
				).format(student_name, course_title),
				"document_type": "LMS Enrollment",
				"document_name": self.name,
				"from_user": self.member,
				"type": "Alert",
				"link": link,
			}
		)
		try:
			make_notification_logs(notification, instructors)
		except Exception:
			frappe.log_error(
				frappe.get_traceback(), "LMS: Course completion instructor notification failed"
			)


def is_admin():
	roles = frappe.get_roles(frappe.session.user)
	admin_roles = ["Moderator", "Course Creator", "Batch Evaluator"]
	for role in admin_roles:
		if role in roles:
			return True
	return False


def update_program_progress(member):
	programs = frappe.get_all("LMS Program Member", {"member": member}, ["parent", "name"])

	for program in programs:
		total_progress = 0
		courses = frappe.get_all("LMS Program Course", {"parent": program.parent}, pluck="course")
		if not courses:
			continue

		for course in courses:
			progress = frappe.db.get_value("LMS Enrollment", {"course": course, "member": member}, "progress")
			progress = progress or 0
			total_progress += progress

		average_progress = ceil(total_progress / len(courses))
		frappe.db.set_value("LMS Program Member", program.name, "progress", average_progress)


def _update_course_enrollments(course, increment=True):
	LMSCourse = frappe.qb.DocType("LMS Course")
	value = 1 if increment else -1
	frappe.qb.update(LMSCourse).set(LMSCourse.enrollments, LMSCourse.enrollments + value).where(
		LMSCourse.name == course
	).run()


@contextmanager
def batched_enrollment_updates():
	"""Coalesce every enrollment write in this block into one write and one dispatch."""
	# A lesson completion writes the enrollment twice: LMS Course Progress.on_update
	# recalculates progress, then save_progress advances current_lesson. Dispatched
	# separately that is two on_updates: two webhook deliveries per completion, where
	# the pre-regression .save() delivered one. Batching restores the single event.
	if getattr(frappe.local, "lms_enrollment_batch", None) is not None:
		yield
		return

	frappe.local.lms_enrollment_batch = {}
	try:
		yield
		batch = frappe.local.lms_enrollment_batch
	finally:
		frappe.local.lms_enrollment_batch = None

	# One enrollment's on_update handler must not strand the rest of the batch unwritten.
	failed = []
	for name, values in batch.items():
		try:
			_write_enrollment(name, values)
		except Exception:
			frappe.log_error(title=f"Enrollment update failed: {name}")
			failed.append(name)

	if failed:
		frappe.throw(_("Could not update enrollments: {0}").format(", ".join(failed)))


def update_enrollment(name: str, values: dict):
	"""Write enrollment fields, firing the save doc events a raw set_value would skip."""
	batch = getattr(frappe.local, "lms_enrollment_batch", None)
	if batch is not None:
		batch.setdefault(name, {}).update(values)
		return

	_write_enrollment(name, values)


def _write_enrollment(name: str, values: dict):
	# Do not turn this back into enrollment.save(). Two near-simultaneous requests
	# (video-ended fires markProgress + trackVideoWatchDuration, which also writes
	# progress) raced there: both .save()s ran check_if_latest() and the second threw
	# TimestampMismatchError, swallowing whichever write arrived second. A raw
	# set_value skips that guard but fires no doc events at all, which is what
	# silently broke On Update webhooks / DocType Event scripts. So: write raw, then
	# dispatch on_update and on_change by hand, in the order .save() would.
	enrollment = frappe.get_doc("LMS Enrollment", name)
	for field in values:
		if not enrollment.meta.get_field(field):
			frappe.throw(_("{0} is not a field on LMS Enrollment").format(field))
		if field in IDENTITY_FIELDS:
			stored_value = enrollment.get(field)
			attempted_value = values[field]
			if (attempted_value or None) != (stored_value or None):
				_throw_identity_field_locked(
					enrollment.name, _(enrollment.meta.get_label(field)), stored_value, attempted_value
				)

	changed = {field: value for field, value in values.items() if enrollment.get(field) != value}
	if not changed:
		return

	# on_change handlers and Value Change notifications read doc_before_save. Rebuild
	# the snapshot from the values we already hold: load_doc_before_save() re-reads the
	# row FOR UPDATE (the lock this write exists to avoid), and a deepcopy would clone
	# the process-cached DocMeta along with it.
	enrollment._doc_before_save = frappe.get_doc(enrollment.as_dict())

	frappe.db.set_value("LMS Enrollment", name, changed, update_modified=False)
	enrollment.update(changed)
	enrollment.run_method("on_update")
	enrollment.run_method("on_change")


def send_inactivity_reminders(target_days=None, member=None, course=None):
	"""N60 & N61: Send inactivity re-engagement reminders.
	- 7-day reminder (N60): Student inactive for 7 days.
	- 14-day reminder (N61): Student inactive for 14 days (final re-engagement).
	"""
	outgoing = frappe.get_cached_value(
		"Email Account", {"default_outgoing": 1, "enable_outgoing": 1}, "name"
	)
	if not (outgoing or frappe.conf.get("mail_login")):
		return []

	from frappe.utils import date_diff, getdate, format_date, nowdate
	from lms.lms.utils import get_lms_route

	filters = {"progress": ["<", 100]}
	if member:
		filters["member"] = member
	if course:
		filters["course"] = course

	enrollments = frappe.get_all(
		"LMS Enrollment",
		filters=filters,
		fields=["name", "member", "course", "progress", "creation", "modified"],
	)

	from lms.lms.utils import get_frontend_url
	app_name = "Stridenex-LMS"
	site_url = get_frontend_url()

	sent_emails = []
	for enr in enrollments:
		latest_progress = frappe.db.get_value(
			"LMS Course Progress",
			{"member": enr.member, "course": enr.course},
			"modified",
			order_by="modified desc",
		)
		last_active_time = latest_progress or enr.modified or enr.creation
		days_inactive = date_diff(nowdate(), getdate(last_active_time))

		should_send_7 = (target_days == 7) or (target_days is None and days_inactive == 7)
		should_send_14 = (target_days == 14) or (target_days is None and days_inactive == 14)

		if not (should_send_7 or should_send_14):
			continue

		student_name = frappe.db.get_value("User", enr.member, "full_name") or enr.member
		course_title = frappe.db.get_value("LMS Course", enr.course, "title") or enr.course
		course_link = f"/course/{enr.course}"

		args = {
			"student_name": student_name,
			"course_title": course_title,
			"progress": int(enr.progress or 0),
			"last_active": format_date(last_active_time, "medium"),
			"site_url": site_url,
			"course_link": course_link,
			"app_name": app_name,
		}

		if should_send_7:
			subject = _("👋 We miss you! Continue learning {0}").format(course_title)
			template = "student_inactivity_7days"
			header_color = "indigo"
		else:
			subject = _("⏰ Final reminder: Your course {0} is waiting!").format(course_title)
			template = "student_inactivity_14days"
			header_color = "purple"

		try:
			frappe.sendmail(
				recipients=enr.member,
				subject=subject,
				template=template,
				args=args,
				header=[subject, header_color],
				retry=3,
			)
			sent_emails.append({
				"member": enr.member,
				"course": enr.course,
				"days": 7 if should_send_7 else 14,
				"subject": subject
			})
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"LMS: Inactivity reminder email failed for {enr.member}")

	return sent_emails

