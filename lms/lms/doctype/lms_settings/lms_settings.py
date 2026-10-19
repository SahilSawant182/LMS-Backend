# Copyright (c) 2021, FOSS United and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, get_url_to_list, validate_email_address, validate_url

from lms.lms.sidebar import validate_sidebar_items


class LMSSettings(Document):
	def validate(self):
		self.validate_google_settings()
		self.validate_signup()
		self.validate_contact_us_details()
		self.validate_lesson_dwell_time()
		validate_sidebar_items(self)

	def validate_lesson_dwell_time(self):
		if cint(self.lesson_dwell_time) < 1:
			frappe.throw(_("Lesson Dwell Time must be at least 1 second."))

	def validate_google_settings(self):
		if self.send_calendar_invite_for_evaluations:
			google_settings = frappe.get_single("Google Settings")

			if not google_settings.enable:
				frappe.throw(
					_("Enable Google API in Google Settings to send calendar invites for evaluations.")
				)

			if not google_settings.client_id or not google_settings.client_secret:
				frappe.throw(
					_(
						"Enter Client Id and Client Secret in Google Settings to send calendar invites for evaluations."
					)
				)

			calendars = frappe.db.count("Google Calendar")
			if not calendars:
				frappe.throw(
					_(
						"Please add <a href='{0}'>{1}</a> for <a href='{2}'>{3}</a> to send calendar invites for evaluations."
					).format(
						get_url_to_list("Google Calendar"),
						frappe.bold("Google Calendar"),
						get_url_to_list("Course Evaluator"),
						frappe.bold("Course Evaluator"),
					)
				)

	def validate_signup(self):
		if self.has_value_changed("disable_signup"):
			frappe.db.set_single_value("Website Settings", "disable_signup", self.disable_signup)

	def validate_contact_us_details(self):
		if self.contact_us_email and not validate_email_address(self.contact_us_email):
			frappe.throw(_("Please enter a valid Contact Us Email."))
		if self.contact_us_url and not validate_url(self.contact_us_url, True, ["http", "https"]):
			frappe.throw(_("Please enter a valid Contact Us URL."))


@frappe.whitelist()
def check_payments_app():
	installed_apps = frappe.get_installed_apps()
	if "payments" not in installed_apps:
		return False
	else:
		filters = {
			"doctype_or_field": "DocField",
			"doc_type": "LMS Settings",
			"field_name": "payment_gateway",
		}
		if frappe.db.exists("Property Setter", filters):
			return True

		link_property = frappe.new_doc("Property Setter")
		link_property.update(filters)
		link_property.property = "fieldtype"
		link_property.value = "Link"
		link_property.save()

		options_property = frappe.new_doc("Property Setter")
		options_property.update(filters)
		options_property.property = "options"
		options_property.value = "Payment Gateway"
		options_property.save()

		return True




@frappe.whitelist()
def get_lms_settings():
    """Get LMS Settings."""

    if not frappe.has_permission("LMS Settings", "read"):
        frappe.throw("Not permitted to read LMS Settings", frappe.PermissionError)

    settings = frappe.get_single("LMS Settings")

    return {
        "success": True,
        "data": settings.as_dict()
    }

@frappe.whitelist(methods=["PUT", "POST"])
def update_lms_settings():
    """Update LMS Settings."""

    if frappe.session.user == "Guest":
        frappe.throw(
            "Login required to update LMS Settings",
            frappe.AuthenticationError
        )

    if not frappe.has_permission("LMS Settings", "write"):
        frappe.throw(
            "Not permitted to update LMS Settings",
            frappe.PermissionError
        )

    data = frappe.request.get_json(silent=True) or {}

    if not data:
        frappe.throw("Request body is required")

    settings = frappe.get_single("LMS Settings")

    # Fields that can be updated through this API.
    allowed_fields = {
        "allow_guest_access",
        "prevent_skipping_videos",
        "send_calendar_invite_for_evaluations",
        "disable_pwa",
        "default_home",
        "unsplash_access_key",
        "livecode_url",
        "send_notification_for_published_courses",
        "send_notification_for_published_batches",
        "show_day_view",
        "show_dashboard",
        "show_courses",
        "show_students",
        "show_assessments",
        "show_live_class",
        "show_discussions",
        "show_emails",
        "enforce_video_completion",
        "enforce_quiz_completion",
        "enforce_assignment_completion",
        "lesson_dwell_time",
        "user_category",
        "disable_signup",
        "custom_signup_content",
        "courses",
        "batches",
        "certified_members",
        "certifications",
        "programming_exercises",
        "jobs",
        "statistics",
        "notifications",
        "sidebar_items",
        "mentor_request_creation",
        "mentor_request_status_update",
        "payment_gateway",
        "default_currency",
        "exception_country",
        "apply_gst",
        "show_usd_equivalent",
        "apply_rounding",
        "send_payment_reminders_for_batch",
        "send_payment_reminders_for_course",
        "certification_template",
        "batch_confirmation_template",
        "payment_reminder_template",
        "meta_description",
        "meta_image",
        "meta_keywords",
        "contact_us_email",
        "contact_us_url",
        "allow_job_posting"
    }

    updated_fields = []

    for field, value in data.items():
        if field in allowed_fields:
            settings.set(field, value)
            updated_fields.append(field)

    if not updated_fields:
        frappe.throw("No valid fields provided for update")

    settings.save()
    frappe.db.commit()

    return {
        "success": True,
        "message": "LMS Settings updated successfully",
        "updated_fields": updated_fields,
        "data": settings.as_dict()
    }