# Copyright (c) 2025, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.desk.doctype.notification_log.notification_log import make_notification_logs
from frappe.model.document import Document

from lms.lms.utils import get_lms_route


class LMSBatchFeedback(Document):
	def after_insert(self):
		"""N67 – System notification to batch instructors when a student submits feedback."""
		self.notify_instructors_of_feedback()

	def notify_instructors_of_feedback(self):
		instructors = frappe.get_all(
			"Course Instructor",
			{"parent": self.batch, "parenttype": "LMS Batch"},
			pluck="instructor",
		)
		if not instructors:
			return

		student_name = frappe.db.get_value("User", self.member, "full_name") or self.member
		batch_title = frappe.db.get_value("LMS Batch", self.batch, "title") or self.batch
		link = get_lms_route(f"batches/{self.batch}")

		notification = frappe._dict(
			{
				"subject": _("📝 {0} submitted feedback for your batch {1}").format(
					frappe.bold(student_name), frappe.bold(batch_title)
				),
				"email_content": _(
					"{0} has submitted feedback for batch '{1}'. "
					"Content rating: {2}/5, Instructor rating: {3}/5, Value rating: {4}/5. "
					"Feedback: {5}"
				).format(
					student_name,
					batch_title,
					self.content,
					self.instructors,
					self.value,
					self.feedback or "(no comment)",
				),
				"document_type": "LMS Batch Feedback",
				"document_name": self.name,
				"from_user": self.member,
				"type": "Alert",
				"link": link,
			}
		)
		try:
			make_notification_logs(notification, instructors)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "LMS: Batch feedback instructor notification failed")


import frappe
from frappe import _


@frappe.whitelist()
def submit_batch_feedback(
    batch,
    feedback,
    content,
    instructors,
    value,
    member=None
):
    """
    Submit feedback for an LMS Batch.

    Required:
        batch
        feedback
        content
        instructors
        value

    Optional:
        member
    """

    # Use logged-in user if member is not provided
    member = member or frappe.session.user

    # Guest users cannot submit feedback
    if member == "Guest":
        frappe.throw(_("You must be logged in to submit feedback."))

    # Validate batch
    if not frappe.db.exists("LMS Batch", batch):
        frappe.throw(_("Batch {0} does not exist.").format(batch))

    # Validate member
    if not frappe.db.exists("User", member):
        frappe.throw(_("Member {0} does not exist.").format(member))

    # Validate feedback
    if not feedback or not feedback.strip():
        frappe.throw(_("Feedback is required."))

    # Validate ratings
    ratings = {
        "content": content,
        "instructors": instructors,
        "value": value
    }

    for fieldname, rating in ratings.items():
        try:
            rating = float(rating)
        except (TypeError, ValueError):
            frappe.throw(
                _("{0} rating must be a number.").format(
                    fieldname.title()
                )
            )

        if rating < 1 or rating > 5:
            frappe.throw(
                _("{0} rating must be between 1 and 5.").format(
                    fieldname.title()
                )
            )

    # Prevent duplicate feedback from same member for same batch
    existing = frappe.db.exists(
        "LMS Batch Feedback",
        {
            "member": member,
            "batch": batch
        }
    )

    if existing:
        frappe.throw(
            _("You have already submitted feedback for this batch.")
        )

    # Create feedback
    doc = frappe.get_doc({
        "doctype": "LMS Batch Feedback",
        "member": member,
        "batch": batch,
        "feedback": feedback.strip(),
        "content": content,
        "instructors": instructors,
        "value": value
    })

    doc.insert(ignore_permissions=True)
    frappe.db.commit()

    return {
        "success": True,
        "message": "Feedback submitted successfully.",
        "data": {
            "name": doc.name,
            "member": doc.member,
            "member_name": doc.member_name,
            "member_image": doc.member_image,
            "batch": doc.batch,
            "feedback": doc.feedback,
            "content": doc.content,
            "instructors": doc.instructors,
            "value": doc.value,
            "creation": doc.creation
        }
    }

@frappe.whitelist()
def get_batch_feedback(batch, page=1, limit=20):
    """
    Get feedback submitted for an LMS Batch.
    """

    if not frappe.db.exists("LMS Batch", batch):
        frappe.throw(_("Batch {0} does not exist.").format(batch))

    try:
        page = int(page)
        limit = int(limit)
    except (TypeError, ValueError):
        frappe.throw(_("Page and limit must be numbers."))

    if page < 1:
        page = 1

    if limit < 1:
        limit = 20

    if limit > 100:
        limit = 100

    start = (page - 1) * limit

    feedback_list = frappe.get_all(
        "LMS Batch Feedback",
        filters={
            "batch": batch
        },
        fields=[
            "name",
            "member",
            "member_name",
            "member_image",
            "batch",
            "feedback",
            "content",
            "instructors",
            "value",
            "creation"
        ],
        order_by="creation desc",
        start=start,
        page_length=limit
    )

    total = frappe.db.count(
        "LMS Batch Feedback",
        filters={
            "batch": batch
        }
    )

    return {
        "success": True,
        "data": feedback_list,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "total_pages": (total + limit - 1) // limit
        }
    }


@frappe.whitelist()
def get_batch_feedback_summary(batch):

    if not frappe.db.exists("LMS Batch", batch):
        frappe.throw(_("Batch does not exist."))

    result = frappe.db.sql(
        """
        SELECT
            COUNT(*) AS total_reviews,
            COALESCE(AVG(content), 0) AS content_rating,
            COALESCE(AVG(instructors), 0) AS instructor_rating,
            COALESCE(AVG(value), 0) AS value_rating
        FROM `tabLMS Batch Feedback`
        WHERE batch = %s
        """,
        (batch,),
        as_dict=True
    )[0]

    total = result.total_reviews or 0

    if total:
        overall = (
            float(result.content_rating)
            + float(result.instructor_rating)
            + float(result.value_rating)
        ) / 3
    else:
        overall = 0

    return {
        "success": True,
        "data": {
            "batch": batch,
            "total_reviews": total,
            "content_rating": round(
                float(result.content_rating), 2
            ),
            "instructor_rating": round(
                float(result.instructor_rating), 2
            ),
            "value_rating": round(
                float(result.value_rating), 2
            ),
            "overall_rating": round(overall, 2)
        }
    }