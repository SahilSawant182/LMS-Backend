# Copyright (c) 2024, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.desk.doctype.notification_log.notification_log import make_notification_logs
from frappe.model.document import Document

from lms.lms.doctype.lms_badge.lms_badge import eval_condition


class LMSBadgeAssignment(Document):
	def validate(self):
		self.validate_duplicate_badge_assignment()
		self.validate_badge_criteria()
		self.validate_owner()

	def after_insert(self):
		"""N4 – Notify student via system notification and email when a badge is awarded."""
		self.send_badge_system_notification()
		self.send_badge_award_email()

	def send_badge_system_notification(self):
		"""In-app system notification to the badge recipient."""
		badge_title = frappe.db.get_value("LMS Badge", self.badge, "title") or self.badge
		notification = frappe._dict(
			{
				"subject": _("🏅 You earned the {0} badge!").format(frappe.bold(badge_title)),
				"email_content": _(
					"Congratulations! You have been awarded the '{0}' badge. Keep up the great work!"
				).format(badge_title),
				"document_type": "LMS Badge Assignment",
				"document_name": self.name,
				"from_user": frappe.session.user,
				"type": "Alert",
				"link": f"/users/{frappe.db.get_value('User', self.member, 'username') or self.member}",
			}
		)
		try:
			make_notification_logs(notification, [self.member])
		except Exception:
			frappe.log_error(frappe.get_traceback(), "LMS: Badge system notification failed")

	def send_badge_award_email(self):
		"""Email the badge recipient with badge details."""
		outgoing_email_account = frappe.get_cached_value(
			"Email Account", {"default_outgoing": 1, "enable_outgoing": 1}, "name"
		)
		if not (outgoing_email_account or frappe.conf.get("mail_login")):
			return

		badge_details = frappe.db.get_value(
			"LMS Badge",
			self.badge,
			["title", "image", "description"],
			as_dict=True,
		)
		if not badge_details:
			return

		student_name = frappe.db.get_value("User", self.member, "full_name") or self.member
		student_username = frappe.db.get_value("User", self.member, "username") or self.member
		app_name = frappe.db.get_single_value("Website Settings", "app_name") or "LMS"
		site_url = frappe.utils.get_url()
		profile_link = f"{site_url}/users/{student_username}"

		subject = _("🏅 You earned the {0} badge!").format(badge_details.title)
		args = {
			"student_name": student_name,
			"badge_title": badge_details.title,
			"badge_image": f"{site_url}{badge_details.image}" if badge_details.image else None,
			"badge_description": badge_details.description,
			"profile_link": profile_link,
			"app_name": app_name,
		}

		try:
			frappe.sendmail(
				recipients=self.member,
				subject=subject,
				template="badge_awarded",
				args=args,
				header=[subject, "green"],
				retry=3,
			)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "LMS: Badge award email failed")

	def validate_owner(self):
		event = frappe.db.get_value("LMS Badge", self.badge, "event")
		if event == "Manual Assignment":
			roles = frappe.get_roles(frappe.session.user)
			admins = ["Moderator", "Course Creator", "Batch Evaluator"]
			if not any(role in roles for role in admins):
				frappe.throw(_("You must be an Admin to assign badges to users."))

	def validate_duplicate_badge_assignment(self):
		grant_only_once = frappe.db.get_value("LMS Badge", self.badge, "grant_only_once")
		if not grant_only_once:
			return

		if frappe.db.exists(
			"LMS Badge Assignment",
			{"badge": self.badge, "member": self.member, "name": ["!=", self.name]},
		):
			frappe.throw(
				_("Badge {0} has already been assigned to this {1}.").format(self.badge, self.member)
			)

	def validate_badge_criteria(self):
		badge_details = frappe.db.get_value(
			"LMS Badge", self.badge, ["reference_doctype", "user_field", "condition", "enabled"], as_dict=True
		)

		if not badge_details:
			return

		if not badge_details.enabled and (self.is_new() or self.has_value_changed("badge")):
			frappe.throw(_("Badge {0} is disabled.").format(self.badge))

		if badge_details.reference_doctype and badge_details.user_field and badge_details.condition:
			user_fieldname = frappe.db.get_value(
				"DocField",
				{"parent": badge_details.reference_doctype, "fieldname": badge_details.user_field},
				"fieldname",
			)

			documents = frappe.get_all(
				badge_details.reference_doctype,
				{user_fieldname: self.member},
			)

			for document in documents:
				reference_value = eval_condition(
					frappe.get_doc(badge_details.reference_doctype, document.name),
					badge_details.condition,
				)
				if reference_value:
					return

			frappe.throw(_("Member does not meet the criteria for the badge {0}.").format(self.badge))



import frappe
from frappe import _
from frappe.utils import getdate, today


BADGE_ASSIGNMENT_DOCTYPE = "LMS Badge Assignment"


def get_badge_assignment_linked_fields(member, badge):
    """Fetch member and badge details for the assignment."""

    if not frappe.db.exists("User", member):
        frappe.throw(_("User {0} does not exist").format(member))

    if not frappe.db.exists("LMS Badge", badge):
        frappe.throw(_("LMS Badge {0} does not exist").format(badge))

    user = frappe.get_doc("User", member)
    badge_doc = frappe.get_doc("LMS Badge", badge)

    if not badge_doc.image:
        frappe.throw(_("The selected badge does not have an image"))

    if not badge_doc.description:
        frappe.throw(_("The selected badge does not have a description"))

    return {
        "member_name": user.full_name,
        "member_username": user.get("username"),
        "member_image": user.get("user_image"),
        "badge_image": badge_doc.image,
        "badge_description": badge_doc.description,
    }


@frappe.whitelist()
def create_badge_assignment(member, badge, issued_on=None):
    """Create an LMS Badge Assignment."""

    if not member or not badge:
        frappe.throw(_("Member and Badge are required"))

    doc = frappe.get_doc({
        "doctype": BADGE_ASSIGNMENT_DOCTYPE,
        "member": member,
        "badge": badge,
        "issued_on": getdate(issued_on) if issued_on else today(),
    })

    # Populate the linked/read-only fields on the server.
    linked_fields = get_badge_assignment_linked_fields(member, badge)

    for field, value in linked_fields.items():
        doc.set(field, value)

    doc.insert()

    return {
        "success": True,
        "message": "Badge assigned successfully",
        "data": doc.as_dict(),
    }


@frappe.whitelist()
def get_badge_assignment(name):
    """Get one badge assignment by document name."""

    if not name:
        frappe.throw(_("Assignment name is required"))

    doc = frappe.get_doc(BADGE_ASSIGNMENT_DOCTYPE, name)
    doc.check_permission("read")

    return {
        "success": True,
        "data": doc.as_dict(),
    }


@frappe.whitelist()
def get_badge_assignment_list(
    member=None,
    badge=None,
    issued_on=None,
    limit_start=0,
    limit_page_length=20,
):
    """List badge assignments with optional filters."""

    filters = {}

    if member:
        filters["member"] = member

    if badge:
        filters["badge"] = badge

    if issued_on:
        filters["issued_on"] = getdate(issued_on)

    limit_start = max(0, int(limit_start))
    limit_page_length = min(max(1, int(limit_page_length)), 100)

    assignments = frappe.get_list(
        BADGE_ASSIGNMENT_DOCTYPE,
        filters=filters,
        fields=[
            "name",
            "member",
            "member_name",
            "member_username",
            "member_image",
            "issued_on",
            "badge",
            "badge_image",
            "badge_description",
            "creation",
        ],
        order_by="creation desc",
        start=limit_start,
        page_length=limit_page_length,
    )

    return {
        "success": True,
        "count": len(assignments),
        "data": assignments,
    }


@frappe.whitelist()
def update_badge_assignment(
    name,
    member=None,
    badge=None,
    issued_on=None,
):
    """Update an existing badge assignment."""

    if not name:
        frappe.throw(_("Assignment name is required"))

    doc = frappe.get_doc(BADGE_ASSIGNMENT_DOCTYPE, name)
    doc.check_permission("write")

    new_member = member if member is not None else doc.member
    new_badge = badge if badge is not None else doc.badge

    if member is not None:
        doc.member = member

    if badge is not None:
        doc.badge = badge

    if issued_on is not None:
        doc.issued_on = getdate(issued_on)

    # Refresh linked fields if the member or badge changes.
    if member is not None or badge is not None:
        linked_fields = get_badge_assignment_linked_fields(
            new_member, new_badge
        )

        for field, value in linked_fields.items():
            doc.set(field, value)

    doc.save()

    return {
        "success": True,
        "message": "Badge assignment updated successfully",
        "data": doc.as_dict(),
    }


@frappe.whitelist()
def delete_badge_assignment(name):
    """Delete a badge assignment."""

    if not name:
        frappe.throw(_("Assignment name is required"))

    doc = frappe.get_doc(BADGE_ASSIGNMENT_DOCTYPE, name)
    doc.delete()

    return {
        "success": True,
        "message": "Badge assignment deleted successfully",
        "name": name,
    }