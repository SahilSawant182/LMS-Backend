# Copyright (c) 2021, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.desk.doctype.notification_log.notification_log import make_notification_logs
from frappe.model.document import Document
from frappe.utils import cint

from lms.lms.utils import get_lms_route


class LMSCourseReview(Document):
	def validate(self):
		self.validate_enrollment()
		self.validate_if_already_reviewed()

	def validate_enrollment(self):
		enrollment = frappe.db.exists("LMS Enrollment", {"course": self.course, "member": self.owner})
		if not enrollment:
			frappe.throw(_("You must be enrolled in the course to submit a review"))

	def validate_if_already_reviewed(self):
		if frappe.db.exists("LMS Course Review", {"course": self.course, "owner": self.owner}):
			frappe.throw(_("You have already reviewed this course"))

	def after_insert(self):
		"""N20 – Notify the course instructors when a student leaves a review."""
		self.notify_instructors_of_review()

	def notify_instructors_of_review(self):
		instructors = frappe.get_all(
			"Course Instructor",
			{"parent": self.course, "parenttype": "LMS Course"},
			pluck="instructor",
		)
		if not instructors:
			return

		course_title = frappe.db.get_value("LMS Course", self.course, "title") or self.course
		reviewer_name = frappe.db.get_value("User", self.owner, "full_name") or self.owner
		out_of = 5
		stars = round(self.rating * out_of)
		link = get_lms_route(f"courses/{self.course}")

		notification = frappe._dict(
			{
				"subject": _("⭐ {0} rated your course {1} ({2}/{3} stars)").format(
					frappe.bold(reviewer_name), frappe.bold(course_title), stars, out_of
				),
				"email_content": _(
					"{0} has just left a {1}-star review on your course '{2}': {3}"
				).format(reviewer_name, stars, course_title, self.review or "(no comment)"),
				"document_type": "LMS Course Review",
				"document_name": self.name,
				"from_user": self.owner,
				"type": "Alert",
				"link": link,
			}
		)
		try:
			make_notification_logs(notification, instructors)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "LMS: Course review instructor notification failed")


import frappe
from frappe import _
from frappe.utils import cint, flt


DOCTYPE = "LMS Course Review"


def validate_course_review(course, rating):
    """Validate course and rating."""

    if not course:
        frappe.throw(_("Course is required."))

    if not frappe.db.exists("LMS Course", course):
        frappe.throw(_("Course {0} does not exist.").format(course))

    if rating is None or rating == "":
        frappe.throw(_("Rating is required."))

    rating = flt(rating)

    if rating < 0 or rating > 5:
        frappe.throw(_("Rating must be between 0 and 5."))

    return rating


@frappe.whitelist(methods=["POST"])
def create_course_review(course, rating, review=None):
    """Create a course review."""

    rating = validate_course_review(course, rating)

    doc = frappe.get_doc({
        "doctype": DOCTYPE,
        "course": course,
        "rating": rating,
        "review": review
    })

    # Uses the current user's normal DocType permissions.
    doc.insert()

    return {
        "success": True,
        "message": "Course review created successfully.",
        "data": {
            "name": doc.name,
            "course": doc.course,
            "rating": doc.rating,
            "review": doc.review,
            "owner": doc.owner,
            "creation": doc.creation
        }
    }


@frappe.whitelist(methods=["GET"])
def get_course_review(name):
    """Get a single course review."""

    if not frappe.db.exists(DOCTYPE, name):
        frappe.throw(
            _("Course review {0} does not exist.").format(name),
            frappe.DoesNotExistError
        )

    doc = frappe.get_doc(DOCTYPE, name)
    doc.check_permission("read")

    return {
        "success": True,
        "data": {
            "name": doc.name,
            "course": doc.course,
            "rating": doc.rating,
            "review": doc.review,
            "owner": doc.owner,
            "creation": doc.creation,
            "modified": doc.modified
        }
    }


@frappe.whitelist(methods=["GET"])
def get_course_review_list(
    course=None,
    rating=None,
    limit_start=0,
    limit_page_length=20
):
    """Get course reviews with optional filters."""

    filters = {}

    if course:
        filters["course"] = course

    if rating is not None and rating != "":
        rating = flt(rating)

        if rating < 0 or rating > 5:
            frappe.throw(_("Rating must be between 0 and 5."))

        filters["rating"] = rating

    limit_start = max(cint(limit_start), 0)
    limit_page_length = min(max(cint(limit_page_length), 1), 100)

    reviews = frappe.get_list(
        DOCTYPE,
        filters=filters,
        fields=[
            "name",
            "course",
            "rating",
            "review",
            "owner",
            "creation",
            "modified"
        ],
        order_by="creation desc",
        start=limit_start,
        page_length=limit_page_length
    )

    return {
        "success": True,
        "count": len(reviews),
        "data": reviews
    }


@frappe.whitelist(methods=["PUT", "PATCH", "POST"])
def update_course_review(name, course=None, rating=None, review=None):
    """Update an existing course review."""

    if not frappe.db.exists(DOCTYPE, name):
        frappe.throw(
            _("Course review {0} does not exist.").format(name),
            frappe.DoesNotExistError
        )

    doc = frappe.get_doc(DOCTYPE, name)

    # Enforce the user's normal write permissions.
    doc.check_permission("write")

    new_course = course if course is not None else doc.course
    new_rating = rating if rating is not None else doc.rating

    new_rating = validate_course_review(new_course, new_rating)

    doc.course = new_course
    doc.rating = new_rating

    if review is not None:
        doc.review = review

    doc.save()

    return {
        "success": True,
        "message": "Course review updated successfully.",
        "data": {
            "name": doc.name,
            "course": doc.course,
            "rating": doc.rating,
            "review": doc.review,
            "owner": doc.owner,
            "modified": doc.modified
        }
    }


@frappe.whitelist(methods=["DELETE", "POST"])
def delete_course_review(name):
    """Delete an existing course review."""

    if not frappe.db.exists(DOCTYPE, name):
        frappe.throw(
            _("Course review {0} does not exist.").format(name),
            frappe.DoesNotExistError
        )

    doc = frappe.get_doc(DOCTYPE, name)
    doc.check_permission("delete")

    doc.delete()

    return {
        "success": True,
        "message": "Course review deleted successfully.",
        "name": name
    }