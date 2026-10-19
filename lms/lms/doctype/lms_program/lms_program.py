# Copyright (c) 2024, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from lms.lms.doctype.lms_content_author.lms_content_author import AuthoredDocument
from lms.lms.permissions import has_authored_content_permission
from lms.lms.utils import guest_access_allowed

# The roles this doctype has always treated as its authoring population. The role
# still admits them to the question; `authors` now decides the answer.
PROGRAM_AUTHORING_ROLES = ("Moderator", "Course Creator")

# The types the published-or-enrolled rule answers. Everything else -- `email` and
# `share` included -- is an authoring ask, exactly as before this change.
PROGRAM_READ_PTYPES = ("read", "select", "print")


class LMSProgram(AuthoredDocument, Document):
	def validate(self):
		self.validate_program_courses()
		self.validate_program_members()
		self.update_count()

	def validate_program_courses(self):
		courses = [row.course for row in self.program_courses]
		duplicates = {course for course in courses if courses.count(course) > 1}
		if len(duplicates):
			frappe.throw(
				_("Course {0} has already been added to this program.").format(
					frappe.bold(next(iter(duplicates)))
				)
			)

	def validate_program_members(self):
		members = [row.member for row in self.program_members]
		duplicates = {member for member in members if members.count(member) > 1}
		if len(duplicates):
			frappe.throw(
				_("Member {0} has already been added to this program.").format(
					frappe.bold(next(iter(duplicates)))
				)
			)

	def update_count(self):
		course_count = len(self.program_courses)
		member_count = len(self.program_members)

		if self.course_count != course_count:
			self.course_count = course_count

		if self.member_count != member_count:
			self.member_count = member_count


def has_authoring_role(user: str) -> bool:
	"""Whether `user` belongs to the population that authors programs at all.

	Read by both halves of this module: two copies of a role test is one that drifts.
	"""
	roles = frappe.get_roles(user)
	return any(role in roles for role in PROGRAM_AUTHORING_ROLES)


def has_program_authoring_permission(doc, ptype: str | None, user: str) -> bool:
	"""The authoring half, narrowed to the people named on the program.

	frappe takes one has_permission hook per doctype and this one already holds the
	read rule below, so the shared predicate is composed here rather than registered.
	The role test runs first on purpose: routing a bare System Manager into the shared
	predicate would readmit it through is_site_administrator, which is a widening.
	"""
	if not has_authoring_role(user):
		return False
	return has_authored_content_permission(doc, ptype, user)


def has_permission(doc, ptype="read", user=None):
	user = user or frappe.session.user

	if user == "Guest" and not guest_access_allowed():
		return False

	roles = frappe.get_roles(user)
	if "System Manager" in roles or "Moderator" in roles or "Course Creator" in roles:
		return True

	if ptype not in ("read", "select", "print"):
		return True

	is_enrolled = frappe.db.exists("LMS Program Member", {"parent": doc.name, "member": user})
	if is_enrolled:
		return True

	is_program_published = frappe.db.get_value("LMS Program", doc.name, "published")
	if is_program_published:
		return True

	return False


def get_permission_query_conditions(user=None):
	"""List-read counterpart of has_permission above: published, or a member."""
	user = user or frappe.session.user
	if user == "Administrator":
		return ""

	if user == "Guest" and not guest_access_allowed():
		return "1 = 0"

	roles = frappe.get_roles(user)
	if "System Manager" in roles or "Moderator" in roles or "Course Creator" in roles:
		return ""

	escaped = frappe.db.escape(user)
	return f"""(`tabLMS Program`.published = 1 or `tabLMS Program`.name in (
		select parent from `tabLMS Program Member` where member = {escaped}
	))"""

import json
import frappe
from frappe import _


# ---------------------------------------------------------
# 1. GET PROGRAM LIST
# ---------------------------------------------------------

@frappe.whitelist()
def get_program_list(
    search=None,
    published=None,
    start=0,
    page_length=20
):
    """
    Get paginated LMS Program list.

    API:
    /api/method/stridenex_app.api_stridenex_app.lms.get_program_list
    """

    start = max(0, int(start))
    page_length = min(100, max(1, int(page_length)))

    filters = {}

    if published is not None and published != "":
        filters["published"] = int(published)

    or_filters = None

    if search:
        or_filters = [
            ["title", "like", f"%{search}%"]
        ]

    programs = frappe.get_list(
        "LMS Program",
        filters=filters,
        or_filters=or_filters,
        fields=[
              "name",
            "title",
            "published",
            "enforce_course_order",
            "course_count",
            "member_count",
            "creation",
            "modified"
        ],
        order_by="creation desc",
        start=start,
        page_length=page_length
    )

    total = frappe.db.count(
        "LMS Program",
        filters=filters
    )

    if search:
        total = len(
            frappe.get_list(
                "LMS Program",
                filters=filters,
                or_filters=or_filters,
                fields=["name"]
            )
        )

    return {
        "success": True,
        "message": "Program list fetched successfully",
        "total": total,
        "start": start,
        "page_length": page_length,
        "data": programs
    }


# ---------------------------------------------------------
# 2. GET PROGRAM DETAIL
# ---------------------------------------------------------

@frappe.whitelist()
def get_program_detail(program_title):
    """
    Get one LMS Program with its courses and members.

    program_title is the LMS Program document name.
    """
    
    if program_title:
        program_title = program_title.strip()

    if not program_title:
        frappe.throw(_("Program title is required"))

    if not frappe.db.exists("LMS Program", program_title):
        frappe.throw(_("LMS Program {0} not found").format(program_title))

    doc = frappe.get_doc("LMS Program", program_title)

    # Check document read permission.
    doc.check_permission("read")

    return {
        "success": True,
        "message": "Program detail fetched successfully",
        "data": doc.as_dict()
    }


# ---------------------------------------------------------
# 3. CREATE PROGRAM
# ---------------------------------------------------------

@frappe.whitelist()
def create_program(
    title,
    published=0,
    enforce_course_order=0,
    program_courses=None,
    program_members=None
):
    """
    Create an LMS Program.

    program_courses and program_members accept JSON arrays.
    """

    if not title or not title.strip():
        frappe.throw(_("Program title is required"))

    if frappe.db.exists("LMS Program", title.strip()):
        frappe.throw(_("Program {0} already exists").format(title.strip()))

    # Parse child table JSON.
    if isinstance(program_courses, str):
        program_courses = json.loads(program_courses)

    if isinstance(program_members, str):
        program_members = json.loads(program_members)

    program_courses = program_courses or []
    program_members = program_members or []

    if not isinstance(program_courses, list):
        frappe.throw(_("Program Courses must be a list"))

    if not isinstance(program_members, list):
        frappe.throw(_("Program Members must be a list"))

    doc = frappe.get_doc({
        "doctype": "LMS Program",
        "title": title.strip(),
        "published": int(published),
        "enforce_course_order": int(enforce_course_order),
        "program_courses": program_courses,
        "program_members": program_members
    })

    doc.insert()
    frappe.db.commit()
    

    return {
        "success": True,
        "message": "Program created successfully",
        "data": doc.as_dict()
    }


# ---------------------------------------------------------
# 4. UPDATE PROGRAM
# ---------------------------------------------------------

@frappe.whitelist()
def update_program(
    program_title,
    title=None,
    published=None,
    enforce_course_order=None,
    program_courses=None,
    program_members=None
):
    """
    Update an existing LMS Program.

    Only supplied fields are updated.
    """

    if program_title:
        program_title = program_title.strip()

    if not program_title:
        frappe.throw(_("Program title is required"))

    if not frappe.db.exists("LMS Program", program_title):
        frappe.throw(_("LMS Program {0} not found").format(program_title))

    doc = frappe.get_doc("LMS Program", program_title)

    doc.check_permission("write")

    if title is not None:
        title = title.strip()

        if not title:
            frappe.throw(_("Program title cannot be empty"))

        existing = frappe.db.exists("LMS Program", title)

        if existing and existing != doc.name:
            frappe.throw(_("Program {0} already exists").format(title))

        if title != doc.name:
            frappe.rename_doc("LMS Program", doc.name, title)
            doc = frappe.get_doc("LMS Program", title)

    if published is not None:
        doc.published = int(published)

    if enforce_course_order is not None:
        doc.enforce_course_order = int(enforce_course_order)

    # Replace courses only when the parameter is supplied.
    if program_courses is not None:
        if isinstance(program_courses, str):
            program_courses = json.loads(program_courses)

        if not isinstance(program_courses, list):
            frappe.throw(_("Program Courses must be a list"))

        doc.set("program_courses", program_courses)

    # Replace members only when the parameter is supplied.
    if program_members is not None:
        if isinstance(program_members, str):
            program_members = json.loads(program_members)

        if not isinstance(program_members, list):
            frappe.throw(_("Program Members must be a list"))

        doc.set("program_members", program_members)

    doc.save()
    frappe.db.commit()

    return {
        "success": True,
        "message": "Program updated successfully",
        "data": doc.as_dict()
    }


# ---------------------------------------------------------
# 5. DELETE PROGRAM
# ---------------------------------------------------------

@frappe.whitelist()
def delete_program(program_title):
    """ 
    Delete an LMS Program.
    """

    if program_title:
        program_title = program_title.strip()

    if not program_title:
        frappe.throw(_("Program title is required")) 

    if not frappe.db.exists("LMS Program", program_title):
        frappe.throw(_("LMS Program {0} not found").format(program_title))

    doc = frappe.get_doc("LMS Program", program_title)

    doc.check_permission("delete")

    doc.delete()

    return {
        "success": True,
        "message": "Program deleted successfully",
        "program_title": program_title
    }  