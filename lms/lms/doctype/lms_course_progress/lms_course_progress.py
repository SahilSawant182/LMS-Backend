# Copyright (c) 2021, FOSS United and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from lms.lms.utils import PRIVILEGED_ROLES, recalculate_course_progress


class LMSCourseProgress(Document):
	def validate(self):
		# Guards updates too; before_insert also calls it so member is bound before the
		# insert-time duplicate check below. The call is idempotent.
		self.enforce_member_ownership()

	def before_insert(self):
		self.enforce_member_ownership()
		if (
			self.member
			and self.lesson
			and frappe.db.exists("LMS Course Progress", {"member": self.member, "lesson": self.lesson})
		):
			frappe.throw(
				_("Progress is already recorded for this lesson."),
				frappe.UniqueValidationError,
			)

	def enforce_member_ownership(self):
		"""A non-privileged user may only record progress for their own account.

		Prevents mass-assignment IDOR via the generic REST API, where a student could
		POST a progress row for an arbitrary member and inflate that member's course
		completion. Privileged roles (instructors/moderators, and the server-side
		save_progress flow which runs with ignore_permissions) are exempt.
		"""
		if PRIVILEGED_ROLES & set(frappe.get_roles()):
			return
		if self.member and self.member != frappe.session.user:
			frappe.throw(
				_("You can only record progress for your own account."),
				frappe.PermissionError,
			)
		self.member = frappe.session.user

	def on_update(self):
		recalculate_course_progress(self.course, self.member)

	def after_delete(self):
		recalculate_course_progress(self.course, self.member)




@frappe.whitelist()
def create_course_progress(
    member=None,
    lesson=None,
    status="Incomplete",
    scorm_content=None
):
    """
    Create LMS Course Progress.

    Required:
        member: User ID
        lesson: Course Lesson ID

    Optional:
        status: Complete, Partially Complete, Incomplete
        scorm_content: SCORM content
    """

    try:
        # Validate required fields
        if not member:
            frappe.throw(_("Member is required"))

        if not lesson:
            frappe.throw(_("Lesson is required"))

        # Validate status
        allowed_statuses = [
            "Complete",
            "Partially Complete",
            "Incomplete"
        ]

        if status not in allowed_statuses:
            frappe.throw(
                _("Status must be Complete, Partially Complete, or Incomplete")
            )

        # Validate member
        if not frappe.db.exists("User", member):
            frappe.throw(_("Member does not exist"))

        # Validate lesson
        if not frappe.db.exists("Course Lesson", lesson):
            frappe.throw(_("Course Lesson does not exist"))

        # Get lesson details
        lesson_doc = frappe.get_doc("Course Lesson", lesson)

        chapter = lesson_doc.chapter

        if not chapter:
            frappe.throw(_("Lesson is not linked to a chapter"))

        # Get chapter details
        chapter_doc = frappe.get_doc("Course Chapter", chapter)

        course = chapter_doc.course

        if not course:
            frappe.throw(_("Chapter is not linked to a course"))

        # Prevent duplicate progress records
        existing = frappe.db.exists(
            "LMS Course Progress",
            {
                "member": member,
                "lesson": lesson
            }
        )

        if existing:
            frappe.throw(
                _("Course progress already exists: {0}").format(existing)
            )

        # Create document
        doc = frappe.get_doc({
            "doctype": "LMS Course Progress",
            "member": member,
            "lesson": lesson,
            "chapter": chapter,
            "course": course,
            "status": status,
            "scorm_content": scorm_content
        })

        doc.insert(ignore_permissions=True)

        frappe.db.commit()

        return {
            "success": True,
            "message": "Course progress created successfully",
            "data": doc.as_dict()
        }

    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            "Create LMS Course Progress API Error"
        )
        frappe.db.rollback()
        raise

@frappe.whitelist()
def get_course_progress(
    name=None,
    member=None,
    course=None,
    chapter=None,
    lesson=None,
    status=None,
    limit=20,
    start=0
):
    """
    Get LMS Course Progress records.

    Optional filters:
        name
        member
        course
        chapter
        lesson
        status

    Pagination:
        limit = 20
        start = 0
    """

    try:
        filters = {}

        if name:
            filters["name"] = name

        if member:
            filters["member"] = member

        if course:
            filters["course"] = course

        if chapter:
            filters["chapter"] = chapter

        if lesson:
            filters["lesson"] = lesson

        if status:
            allowed_statuses = [
                "Complete",
                "Partially Complete",
                "Incomplete"
            ]

            if status not in allowed_statuses:
                frappe.throw(_("Invalid status"))

            filters["status"] = status

        limit = max(1, min(int(limit), 100))
        start = max(0, int(start))

        records = frappe.get_all(
            "LMS Course Progress",
            filters=filters,
            fields=[
                "name",
                "member",
                "member_name",
                "status",
                "lesson",
                "chapter",
                "course",
                "is_scorm_chapter",
                "scorm_content",
                "creation",
                "modified"
            ],
            order_by="modified desc",
            limit_start=start,
            limit_page_length=limit
        )

        total = frappe.db.count(
            "LMS Course Progress",
            filters=filters
        )

        return {
            "success": True,
            "total": total,
            "limit": limit,
            "start": start,
            "data": records
        }

    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            "Get LMS Course Progress API Error"
        )
        raise