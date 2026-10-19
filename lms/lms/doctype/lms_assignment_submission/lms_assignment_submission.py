# Copyright (c) 2021, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.desk.doctype.notification_log.notification_log import make_notification_logs
from frappe.model.document import Document
from frappe.utils import validate_url

from lms.lms.html_sanitizer import sanitize_rich_text
from lms.lms.schedule_utils import assert_within_schedule
from lms.lms.utils import PRIVILEGED_ROLES, get_attachable_files, get_lms_route, validate_attachable_file


class LMSAssignmentSubmission(Document):
	def validate(self):
		self.enforce_member_ownership()
		self.enforce_grading_permission()
		self.sanitize_rich_text_fields()
		self.validate_schedule_window()
		self.validate_duplicates()
		self.validate_url()
		validate_attachable_file(self, "assignment_attachment")
		self.validate_status()

	def sanitize_rich_text_fields(self):
		"""Drop form controls the framework's allowlist keeps: `comments` is mailed as
		`email_content`, and both fields render outside the SPA where v-safe-html does not."""
		for field in ("comments", "answer"):
			self.set(field, sanitize_rich_text(self.get(field)))

	def validate_schedule_window(self):
		"""Students cannot create or edit submission content outside the window.

		Privileged roles may still grade (and manage submissions) outside the
		schedule.
		"""
		if PRIVILEGED_ROLES & set(frappe.get_roles()):
			return

		if not self.assignment:
			return

		schedule = frappe.db.get_value(
			"LMS Assignment",
			self.assignment,
			["title", "enable_scheduling", "schedule_start", "schedule_end"],
			as_dict=True,
		)
		if not schedule:
			return

		assert_within_schedule(
			schedule.enable_scheduling,
			schedule.schedule_start,
			schedule.schedule_end,
			label=schedule.title or _("This assignment"),
		)

	def enforce_grading_permission(self):
		"""Only evaluators/instructors may set the grading fields.

		Prevents a student from grading their own submission (e.g. flipping status from
		"Not Graded" to "Pass" via frappe.client.set_value). On create the grading fields
		are reset to their defaults; on update they are reverted to the stored values.
		"""
		if PRIVILEGED_ROLES & set(frappe.get_roles()):
			return

		# Revert grading fields to their stored values on update, or to safe defaults on
		# create / when no baseline is available (fail closed, never fail open).
		previous = None if self.is_new() else self.get_doc_before_save()
		defaults = {"status": "Not Graded", "comments": None, "evaluator": None}
		for field, default in defaults.items():
			setattr(self, field, previous.get(field) if previous else default)

	def enforce_member_ownership(self):
		if PRIVILEGED_ROLES & set(frappe.get_roles()):
			return
		if self.member and self.member != frappe.session.user:
			frappe.throw(
				_("You can only submit assignments for your own account."),
				frappe.PermissionError,
			)
		self.member = frappe.session.user

	def on_update(self):
		self.validate_private_attachments()

	def after_insert(self):
		"""N21 – Notify the course evaluator / instructors when a new assignment is submitted."""
		self.notify_instructor_of_submission()

	def notify_instructor_of_submission(self):
		"""Determine who should be notified and fire an in-app notification."""
		# 1. Try the explicitly set evaluator on the assignment
		evaluator = frappe.db.get_value("LMS Assignment", self.assignment, "evaluator")

		# 2. Fall back to course instructors
		if not evaluator and self.course:
			instructors = frappe.get_all(
				"Course Instructor",
				{"parent": self.course, "parenttype": "LMS Course"},
				pluck="instructor",
			)
		else:
			instructors = [evaluator] if evaluator else []

		if not instructors:
			return

		assignment_title = self.assignment_title or self.assignment
		student_name = frappe.db.get_value("User", self.member, "full_name") or self.member
		link = get_lms_route(f"assignment-submission/{self.assignment}/{self.name}")

		notification = frappe._dict(
			{
				"subject": _("📋 {0} submitted assignment: {1}").format(
					frappe.bold(student_name), frappe.bold(assignment_title)
				),
				"email_content": _(
					"{0} has submitted the assignment '{1}' and it is awaiting your review and grading."
				).format(student_name, assignment_title),
				"document_type": "LMS Assignment Submission",
				"document_name": self.name,
				"from_user": self.member,
				"type": "Alert",
				"link": link,
			}
		)
		try:
			make_notification_logs(notification, instructors)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "LMS: Assignment submission instructor notification failed")

	def validate_duplicates(self):
		if frappe.db.exists(
			"LMS Assignment Submission",
			{"assignment": self.assignment, "member": self.member, "name": ["!=", self.name]},
		):
			title = (
				frappe.db.get_value("Course Lesson", self.lesson, "title")
				if self.lesson
				else frappe.db.get_value("LMS Assignment", self.assignment, "title")
			)
			frappe.throw(_("A submission for {0} by {1} already exists.").format(title, self.member_name))

	def validate_url(self):
		if self.type == "URL" and not validate_url(self.answer, True, ["http", "https"]):
			frappe.throw(_("Please enter a valid URL."))

	def validate_status(self):
		if self.is_new():
			return
		doc_before_save = self.get_doc_before_save()
		if not doc_before_save:
			return
		if doc_before_save.status != self.status or doc_before_save.comments != self.comments:
			self.trigger_update_notification()
			# N24 / N25 – send grading email only when status actually changes
			if doc_before_save.status != self.status and self.status in ("Pass", "Fail"):
				self.send_grading_email()

	def validate_private_attachments(self):
		if self.type == "Text":
			from bs4 import BeautifulSoup

			soup = BeautifulSoup(self.answer, "html.parser")
			images = soup.find_all("img")
			self.attach_images_to_document(images)

	def attach_images_to_document(self, images):
		sources = []
		for img in images:
			src = img.get("src", "")
			if src.startswith("/private/files/"):
				sources.append(src)

		files = get_attachable_files(sources, self, frappe.session.user)
		for src in sources:
			file = files.get(src)
			if file:
				frappe.db.set_value(
					"File",
					file.name,
					{
						"attached_to_doctype": self.doctype,
						"attached_to_name": self.name,
						"attached_to_field": "answer",
					},
				)

	def trigger_update_notification(self):
		notification = frappe._dict(
			{
				"subject": _("The instructor has left a comment on your assignment {0}").format(
					frappe.bold(self.assignment_title)
				),
				"email_content": self.comments,
				"document_type": self.doctype,
				"document_name": self.name,
				"from_user": self.evaluator,
				"type": "Alert",
				"link": get_lms_route(f"assignment-submission/{self.assignment}/{self.name}"),
			}
		)
		make_notification_logs(notification, [self.member])

	def send_grading_email(self):
		"""N24 / N25 – Email the student when their assignment is graded Pass or Fail.
		Uses separate premium HTML templates for each outcome."""
		outgoing = frappe.get_cached_value(
			"Email Account", {"default_outgoing": 1, "enable_outgoing": 1}, "name"
		)
		if not (outgoing or frappe.conf.get("mail_login")):
			return

		student_name = frappe.db.get_value("User", self.member, "full_name") or self.member
		evaluator_name = (
			frappe.db.get_value("User", self.evaluator, "full_name") if self.evaluator else "Your Instructor"
		)
		course_title = ""
		if self.course:
			course_title = frappe.db.get_value("LMS Course", self.course, "title") or ""

		from lms.lms.utils import get_frontend_url
		site_url = get_frontend_url()
		app_name = "Stridenex-LMS"
		submission_link = f"/assignments/{self.assignment}"

		if self.status == "Pass":
			subject = _("✅ You passed the assignment: {0}").format(self.assignment_title)
			template = "assignment_graded_pass"
			header_color = "green"
		else:
			subject = _("📝 Assignment result: {0} — Please resubmit").format(self.assignment_title)
			template = "assignment_graded_fail"
			header_color = "orange"

		args = {
			"student_name": student_name,
			"assignment_title": self.assignment_title or self.assignment,
			"course_title": course_title,
			"evaluator_name": evaluator_name,
			"comments": self.comments or "",
			"submission_link": submission_link,
			"site_url": site_url,
			"app_name": app_name,
		}

		try:
			frappe.sendmail(
				recipients=self.member,
				subject=subject,
				template=template,
				args=args,
				header=[subject, header_color],
				retry=3,
			)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "LMS: Assignment grading email failed")



import frappe


# =========================================================
# COMMON RESPONSE HELPERS
# =========================================================

def success(data=None, message="Success"):
    return {
        "success": True,
        "message": message,
        "data": data
    }


def error(message="Something went wrong", status_code=500):
    frappe.local.response.http_status_code = status_code

    return {
        "success": False,
        "message": message,
        "data": None
    }


# =========================================================
# ASSIGNMENT APIs
# =========================================================

@frappe.whitelist()
def create_assignment(
    title,
    type,
    question,
    course=None,
    grade_assignment=1,
    show_answer=0,
    answer=None
):
    """
    Create LMS Assignment

    Required:
        title
        type
        question

    type:
        Document
        PDF
        URL
        Image
        Text
    """

    try:
        allowed_types = ["Document", "PDF", "URL", "Image", "Text"]

        if type not in allowed_types:
            return error(
                f"Invalid type. Allowed values: {', '.join(allowed_types)}",
                400
            )

        # Duplicate title check
        if frappe.db.exists("LMS Assignment", {"title": title}):
            return error("Assignment with this title already exists", 409)

        # Course validation
        if course and not frappe.db.exists("LMS Course", course):
            return error("Course not found", 404)

        doc = frappe.get_doc({
            "doctype": "LMS Assignment",
            "title": title,
            "type": type,
            "question": question,
            "course": course,
            "grade_assignment": grade_assignment,
            "show_answer": show_answer,
            "answer": answer
        })

        doc.insert(ignore_permissions=True)
        frappe.db.commit()

        return success(
            doc.as_dict(),
            "Assignment created successfully"
        )

    except Exception as e:
        frappe.log_error(
            frappe.get_traceback(),
            "Create Assignment API Error"
        )
        return error(str(e), 500)


# =========================================================
# GET SINGLE ASSIGNMENT
# =========================================================

@frappe.whitelist()
def get_assignment(name):

    try:
        if not frappe.db.exists("LMS Assignment", name):
            return error("Assignment not found", 404)

        doc = frappe.get_doc("LMS Assignment", name)

        data = doc.as_dict()

        # Include submission count
        data["submission_count"] = frappe.db.count(
            "LMS Assignment Submission",
            {"assignment": name}
        )

        return success(
            data,
            "Assignment fetched successfully"
        )

    except Exception as e:
        frappe.log_error(
            frappe.get_traceback(),
            "Get Assignment API Error"
        )
        return error(str(e), 500)


# =========================================================
# GET ASSIGNMENTS
# =========================================================

@frappe.whitelist()
def get_assignments(
    course=None,
    type=None,
    page=1,
    page_size=20
):

    try:
        page = int(page)
        page_size = int(page_size)

        if page < 1:
            page = 1

        if page_size < 1:
            page_size = 20

        if page_size > 100:
            page_size = 100

        filters = {}

        if course:
            filters["course"] = course

        if type:
            filters["type"] = type

        assignments = frappe.get_all(
            "LMS Assignment",
            filters=filters,
            fields=[
                "name",
                "title",
                "type",
                "course",
                "grade_assignment",
                "show_answer",
                "creation",
                "modified"
            ],
            order_by="modified desc",
            limit_start=(page - 1) * page_size,
            limit_page_length=page_size
        )

        total = frappe.db.count(
            "LMS Assignment",
            filters
        )

        return success(
            {
                "assignments": assignments,
                "pagination": {
                    "page": page,
                    "page_size": page_size,
                    "total": total,
                    "total_pages": (total + page_size - 1) // page_size
                }
            },
            "Assignments fetched successfully"
        )

    except Exception as e:
        frappe.log_error(
            frappe.get_traceback(),
            "Get Assignments API Error"
        )
        return error(str(e), 500)


# =========================================================
# UPDATE ASSIGNMENT
# =========================================================

@frappe.whitelist()
def update_assignment(
    name,
    title=None,
    type=None,
    question=None,
    course=None,
    grade_assignment=None,
    show_answer=None,
    answer=None
):

    try:
        if not frappe.db.exists("LMS Assignment", name):
            return error("Assignment not found", 404)

        doc = frappe.get_doc("LMS Assignment", name)

        if title is not None:
            doc.title = title

        if type is not None:
            allowed_types = [
                "Document",
                "PDF",
                "URL",
                "Image",
                "Text"
            ]

            if type not in allowed_types:
                return error(
                    f"Invalid type. Allowed values: {', '.join(allowed_types)}",
                    400
                )

            doc.type = type

        if question is not None:
            doc.question = question

        if course is not None:
            if not frappe.db.exists("LMS Course", course):
                return error("Course not found", 404)

            doc.course = course

        if grade_assignment is not None:
            doc.grade_assignment = grade_assignment

        if show_answer is not None:
            doc.show_answer = show_answer

        if answer is not None:
            doc.answer = answer

        doc.save(ignore_permissions=True)
        frappe.db.commit()

        return success(
            doc.as_dict(),
            "Assignment updated successfully"
        )

    except Exception as e:
        frappe.log_error(
            frappe.get_traceback(),
            "Update Assignment API Error"
        )
        return error(str(e), 500)


# =========================================================
# DELETE ASSIGNMENT
# =========================================================

@frappe.whitelist()
def delete_assignment(name):

    try:
        if not frappe.db.exists("LMS Assignment", name):
            return error("Assignment not found", 404)

        # Check submissions
        submission_count = frappe.db.count(
            "LMS Assignment Submission",
            {"assignment": name}
        )

        if submission_count > 0:
            return error(
                "Cannot delete assignment because submissions exist",
                400
            )

        frappe.delete_doc(
            "LMS Assignment",
            name,
            ignore_permissions=True
        )

        frappe.db.commit()

        return success(
            {"name": name},
            "Assignment deleted successfully"
        )

    except Exception as e:
        frappe.log_error(
            frappe.get_traceback(),
            "Delete Assignment API Error"
        )
        return error(str(e), 500)


# =========================================================
# CREATE ASSIGNMENT SUBMISSION
# =========================================================

@frappe.whitelist()
def create_assignment_submission(
    assignment,
    member,
    answer=None,
    assignment_attachment=None,
    lesson=None
):

    try:

        # Assignment validation
        if not frappe.db.exists("LMS Assignment", assignment):
            return error("Assignment not found", 404)

        assignment_doc = frappe.get_doc(
            "LMS Assignment",
            assignment
        )

        # User validation
        if not frappe.db.exists("User", member):
            return error("Member/User not found", 404)

        # Lesson validation
        if lesson:
            if not frappe.db.exists("Course Lesson", lesson):
                return error("Lesson not found", 404)

        # Prevent duplicate submission
        existing = frappe.db.exists(
            "LMS Assignment Submission",
            {
                "assignment": assignment,
                "member": member
            }
        )

        if existing:
            return error(
                "Assignment has already been submitted by this member",
                409
            )

        # Validate URL/Text answer
        if assignment_doc.type == "URL" and not answer:
            return error(
                "Answer is required for URL assignment",
                400
            )

        if assignment_doc.type == "Text" and not answer:
            return error(
                "Answer is required for Text assignment",
                400
            )

        # Validate attachment
        if assignment_doc.type not in ["URL", "Text"]:
            if not assignment_attachment:
                return error(
                    "Assignment attachment is required",
                    400
                )

        doc = frappe.get_doc({
            "doctype": "LMS Assignment Submission",
            "assignment": assignment,
            "member": member,
            "assignment_attachment": assignment_attachment,
            "answer": answer,
            "lesson": lesson
        })

        doc.insert(ignore_permissions=True)
        frappe.db.commit()

        return success(
            doc.as_dict(),
            "Assignment submitted successfully"
        )

    except Exception as e:
        frappe.log_error(
            frappe.get_traceback(),
            "Create Assignment Submission API Error"
        )
        return error(str(e), 500)


# =========================================================
# GET SINGLE SUBMISSION
# =========================================================

@frappe.whitelist()
def get_assignment_submission(name):

    try:
        if not frappe.db.exists(
            "LMS Assignment Submission",
            name
        ):
            return error("Submission not found", 404)

        doc = frappe.get_doc(
            "LMS Assignment Submission",
            name
        )

        return success(
            doc.as_dict(),
            "Assignment submission fetched successfully"
        )

    except Exception as e:
        frappe.log_error(
            frappe.get_traceback(),
            "Get Assignment Submission API Error"
        )
        return error(str(e), 500)


# =========================================================
# GET SUBMISSIONS
# =========================================================

@frappe.whitelist()
def get_assignment_submissions(
    assignment=None,
    member=None,
    status=None,
    course=None,
    page=1,
    page_size=20
):

    try:

        page = int(page)
        page_size = int(page_size)

        if page < 1:
            page = 1

        if page_size < 1:
            page_size = 20

        if page_size > 100:
            page_size = 100

        filters = {}

        if assignment:
            filters["assignment"] = assignment

        if member:
            filters["member"] = member

        if status:
            filters["status"] = status

        if course:
            filters["course"] = course

        submissions = frappe.get_all(
            "LMS Assignment Submission",
            filters=filters,
            fields=[
                "name",
                "assignment",
                "assignment_title",
                "type",
                "member",
                "member_name",
                "evaluator",
                "status",
                "course",
                "lesson",
                "creation",
                "modified"
            ],
            order_by="modified desc",
            limit_start=(page - 1) * page_size,
            limit_page_length=page_size
        )

        total = frappe.db.count(
            "LMS Assignment Submission",
            filters
        )

        return success(
            {
                "submissions": submissions,
                "pagination": {
                    "page": page,
                    "page_size": page_size,
                    "total": total,
                    "total_pages": (total + page_size - 1) // page_size
                }
            },
            "Assignment submissions fetched successfully"
        )

    except Exception as e:
        frappe.log_error(
            frappe.get_traceback(),
            "Get Assignment Submissions API Error"
        )
        return error(str(e), 500)


# =========================================================
# UPDATE / GRADE SUBMISSION
# =========================================================

@frappe.whitelist()
def update_assignment_submission(
    name,
    status=None,
    evaluator=None,
    comments=None,
    answer=None,
    assignment_attachment=None
):

    try:

        if not frappe.db.exists(
            "LMS Assignment Submission",
            name
        ):
            return error("Submission not found", 404)

        doc = frappe.get_doc(
            "LMS Assignment Submission",
            name
        )

        allowed_statuses = [
            "Pass",
            "Fail",
            "Not Graded",
            "Not Applicable"
        ]

        if status is not None:

            if status not in allowed_statuses:
                return error(
                    f"Invalid status. Allowed values: {', '.join(allowed_statuses)}",
                    400
                )

            doc.status = status

        if evaluator is not None:
            if not frappe.db.exists("User", evaluator):
                return error("Evaluator not found", 404)

            doc.evaluator = evaluator

        if comments is not None:
            doc.comments = comments

        if answer is not None:
            doc.answer = answer

        if assignment_attachment is not None:
            doc.assignment_attachment = assignment_attachment

        doc.save(ignore_permissions=True)
        frappe.db.commit()

        return success(
            doc.as_dict(),
            "Assignment submission updated successfully"
        )

    except Exception as e:
        frappe.log_error(
            frappe.get_traceback(),
            "Update Assignment Submission API Error"
        )
        return error(str(e), 500)


# =========================================================
# DELETE SUBMISSION
# =========================================================

@frappe.whitelist()
def delete_assignment_submission(name):

    try:

        if not frappe.db.exists(
            "LMS Assignment Submission",
            name
        ):
            return error("Submission not found", 404)

        frappe.delete_doc(
            "LMS Assignment Submission",
            name,
            ignore_permissions=True
        )

        frappe.db.commit()

        return success(
            {"name": name},
            "Assignment submission deleted successfully"
        )

    except Exception as e:
        frappe.log_error(
            frappe.get_traceback(),
            "Delete Assignment Submission API Error"
        )
        return error(str(e), 500)

