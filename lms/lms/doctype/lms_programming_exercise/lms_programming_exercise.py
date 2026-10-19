# Copyright (c) 2025, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from lms.lms.doctype.lms_content_author.lms_content_author import AuthoredDocument


class LMSProgrammingExercise(AuthoredDocument, Document):
	def validate(self):
		self.validate_test_cases()

	def validate_test_cases(self):
		if not self.test_cases:
			frappe.throw(_("At least one test case is required for the programming exercise."))


import frappe
from frappe import _


DOCTYPE = "LMS Programming Exercise"


def validate_programming_exercise_data(data):
    """Validate programming exercise fields."""

    if not data.get("title"):
        frappe.throw(_("Title is required"))

    if not data.get("problem_statement"):
        frappe.throw(_("Problem Statement is required"))

    if data.get("language") and data["language"] not in [
        "Python",
        "JavaScript",
        "Rust",
        "Go",
    ]:
        frappe.throw(_("Invalid programming language"))

    test_cases = data.get("test_cases") or []

    if isinstance(test_cases, str):
        import json
        test_cases = json.loads(test_cases)

    if not isinstance(test_cases, list):
        frappe.throw(_("Test Cases must be a list"))

    data["test_cases"] = test_cases


def get_programming_exercise_data(doc):
    """Return programming exercise details."""

    return {
        "name": doc.name,
        "title": doc.title,
        "problem_statement": doc.problem_statement,
        "language": doc.language,
        "test_cases": [
            {
                "name": row.name,
                "input": getattr(row, "input", None),
                "output": getattr(row, "output", None),
            }
            for row in doc.test_cases
        ],
        "creation": doc.creation,
        "modified": doc.modified,
    }


# --------------------------------------------------
# CREATE PROGRAMMING EXERCISE
# --------------------------------------------------

@frappe.whitelist()
def create_programming_exercise(
    title,
    problem_statement,
    language="Python",
    test_cases=None,
):
    """Create an LMS Programming Exercise."""

    frappe.only_for(
        ["System Manager", "Course Creator", "Moderator"]
    )

    if isinstance(test_cases, str):
        import json
        test_cases = json.loads(test_cases)

    data = {
        "title": title,
        "problem_statement": problem_statement,
        "language": language,
        "test_cases": test_cases or [],
    }

    validate_programming_exercise_data(data)

    doc = frappe.get_doc({
        "doctype": DOCTYPE,
        **data,
    })

    doc.insert()

    return {
        "status": "success",
        "message": "Programming exercise created successfully",
        "data": get_programming_exercise_data(doc),
    }


# --------------------------------------------------
# GET SINGLE PROGRAMMING EXERCISE
# --------------------------------------------------

@frappe.whitelist()
def get_programming_exercise(name):
    """Fetch one programming exercise by document name."""

    doc = frappe.get_doc(DOCTYPE, name)

    doc.check_permission("read")

    return {
        "status": "success",
        "data": get_programming_exercise_data(doc),
    }


# --------------------------------------------------
# LIST PROGRAMMING EXERCISES
# --------------------------------------------------

@frappe.whitelist()
def get_programming_exercise_list(
    txt=None,
    language=None,
    start=0,
    page_length=20,
):
    """List programming exercises with pagination and filters."""

    start = max(0, int(start))
    page_length = min(100, max(1, int(page_length)))

    filters = {}

    if language:
        filters["language"] = language

    if txt:
        filters["title"] = ["like", f"%{txt}%"]

    exercises = frappe.get_list(
        DOCTYPE,
        filters=filters,
        fields=[
            "name",
            "title",
            "language",
            "creation",
            "modified",
        ],
        order_by="creation desc",
        start=start,
        page_length=page_length,
    )

    return {
        "status": "success",
        "count": len(exercises),
        "data": exercises,
    }


# --------------------------------------------------
# UPDATE PROGRAMMING EXERCISE
# --------------------------------------------------

@frappe.whitelist()
def update_programming_exercise(
    name,
    title=None,
    problem_statement=None,
    language=None,
    test_cases=None,
):
    """Update an existing programming exercise."""

    doc = frappe.get_doc(DOCTYPE, name)

    doc.check_permission("write")

    if isinstance(test_cases, str):
        import json
        test_cases = json.loads(test_cases)

    data = {}

    if title is not None:
        data["title"] = title

    if problem_statement is not None:
        data["problem_statement"] = problem_statement

    if language is not None:
        data["language"] = language

    if test_cases is not None:
        data["test_cases"] = test_cases

    validate_programming_exercise_data({
        "title": data.get("title", doc.title),
        "problem_statement": data.get(
            "problem_statement", doc.problem_statement
        ),
        "language": data.get("language", doc.language),
        "test_cases": data.get("test_cases", doc.test_cases),
    })

    for field, value in data.items():
        setattr(doc, field, value)

    doc.save()

    return {
        "status": "success",
        "message": "Programming exercise updated successfully",
        "data": get_programming_exercise_data(doc),
    }


# --------------------------------------------------
# DELETE PROGRAMMING EXERCISE
# --------------------------------------------------

@frappe.whitelist()
def delete_programming_exercise(name):
    """Delete a programming exercise."""

    doc = frappe.get_doc(DOCTYPE, name)

    doc.check_permission("delete")

    doc.delete()

    return {
        "status": "success",
        "message": "Programming exercise deleted successfully",
        "name": name,
    }


# --------------------------------------------------
# PROGRAMMING EXERCISE DROPDOWN
# --------------------------------------------------

@frappe.whitelist()
def get_programming_exercise_dropdown(
    txt=None,
    language=None,
    limit=50,
):
    """Return programming exercises for dropdowns."""

    limit = min(100, max(1, int(limit)))

    filters = {}

    if language:
        filters["language"] = language

    if txt:
        filters["title"] = ["like", f"%{txt}%"]

    return frappe.get_list(
        DOCTYPE,
        filters=filters,
        fields=["name", "title", "language"],
        order_by="title asc",
        page_length=limit,
    )

import json
import frappe
from frappe import _


SUBMISSION_DOCTYPE = "LMS Programming Exercise Submission"


def get_submission_response(doc):
    """Format programming exercise submission response."""

    return {
        "name": doc.name,
        "exercise": doc.exercise,
        "exercise_title": doc.exercise_title,
        "member": doc.member,
        "member_name": doc.member_name,
        "member_image": doc.member_image,
        "status": doc.status,
        "code": doc.code,
        "test_cases": [
            row.as_dict()
            for row in doc.test_cases
        ],
        "creation": doc.creation,
        "modified": doc.modified,
    }


def parse_test_cases(test_cases):
    """Parse test cases supplied as JSON."""

    if test_cases is None:
        return None

    if isinstance(test_cases, str):
        try:
            test_cases = json.loads(test_cases)
        except json.JSONDecodeError:
            frappe.throw(_("Test Cases must contain valid JSON"))

    if not isinstance(test_cases, list):
        frappe.throw(_("Test Cases must be a list"))

    return test_cases


def validate_submission(exercise, member, code, status=None):
    """Validate submission fields."""

    if not exercise:
        frappe.throw(_("Exercise is required"))

    if not frappe.db.exists("LMS Programming Exercise", exercise):
        frappe.throw(_("Programming Exercise does not exist"))

    if not member:
        frappe.throw(_("Member is required"))

    if not frappe.db.exists("User", member):
        frappe.throw(_("Member does not exist"))

    if not code or not code.strip():
        frappe.throw(_("Code is required"))

    if status and status not in ["Passed", "Failed"]:
        frappe.throw(_("Status must be Passed or Failed"))


def validate_submission_owner(doc):
    """Allow students to access only their own submissions."""

    if "System Manager" in frappe.get_roles():
        return

    if "Moderator" in frappe.get_roles():
        return

    if "Course Creator" in frappe.get_roles():
        return

    if "Batch Evaluator" in frappe.get_roles():
        return

    if "LMS Student" in frappe.get_roles():
        if doc.member != frappe.session.user:
            frappe.throw(
                _("You can access only your own submissions"),
                frappe.PermissionError,
            )
        return

    frappe.throw(
        _("You do not have permission to access submissions"),
        frappe.PermissionError,
    )


# --------------------------------------------------
# CREATE SUBMISSION
# --------------------------------------------------

@frappe.whitelist()
def create_programming_exercise_submission(
    exercise,
    code,
    test_cases=None,
):
    """Create a programming exercise submission for the logged-in user."""

    if "LMS Student" not in frappe.get_roles() and not any(
        role in frappe.get_roles()
        for role in [
            "System Manager",
            "Moderator",
            "Course Creator",
            "Batch Evaluator",
        ]
    ):
        frappe.throw(
            _("You do not have permission to submit code"),
            frappe.PermissionError,
        )

    member = frappe.session.user

    test_cases = parse_test_cases(test_cases)

    validate_submission(
        exercise=exercise,
        member=member,
        code=code,
    )

    doc = frappe.get_doc({
        "doctype": SUBMISSION_DOCTYPE,
        "exercise": exercise,
        "member": member,
        "code": code,
        "test_cases": test_cases or [],
    })

    doc.insert()

    return {
        "status": "success",
        "message": "Programming exercise submission created successfully",
        "data": get_submission_response(doc),
    }


# --------------------------------------------------
# GET SINGLE SUBMISSION
# --------------------------------------------------

@frappe.whitelist()
def get_programming_exercise_submission(name):
    """Get a submission by document name."""

    doc = frappe.get_doc(SUBMISSION_DOCTYPE, name)

    validate_submission_owner(doc)
    doc.check_permission("read")

    return {
        "status": "success",
        "data": get_submission_response(doc),
    }


# --------------------------------------------------
# LIST SUBMISSIONS
# --------------------------------------------------

@frappe.whitelist()
def get_programming_exercise_submission_list(
    exercise=None,
    member=None,
    status=None,
    start=0,
    page_length=20,
):
    """List programming exercise submissions with filters."""

    start = max(0, int(start))
    page_length = min(100, max(1, int(page_length)))

    roles = frappe.get_roles()

    is_privileged = any(
        role in roles
        for role in [
            "System Manager",
            "Moderator",
            "Course Creator",
            "Batch Evaluator",
        ]
    )

    filters = {}

    if not is_privileged:
        if "LMS Student" not in roles:
            frappe.throw(
                _("You do not have permission to view submissions"),
                frappe.PermissionError,
            )

        # Students can view only their own submissions.
        filters["member"] = frappe.session.user

    elif member:
        filters["member"] = member

    if exercise:
        filters["exercise"] = exercise

    if status:
        if status not in ["Passed", "Failed"]:
            frappe.throw(_("Invalid submission status"))

        filters["status"] = status

    submissions = frappe.get_list(
        SUBMISSION_DOCTYPE,
        filters=filters,
        fields=[
            "name",
            "exercise",
            "exercise_title",
            "member",
            "member_name",
            "member_image",
            "status",
            "creation",
            "modified",
        ],
        order_by="creation desc",
        start=start,
        page_length=page_length,
    )

    return {
        "status": "success",
        "count": len(submissions),
        "data": submissions,
    }


# --------------------------------------------------
# UPDATE SUBMISSION
# --------------------------------------------------

@frappe.whitelist()
def update_programming_exercise_submission(
    name,
    code=None,
    status=None,
    test_cases=None,
):
    """Update submission code, status, or test case results."""

    doc = frappe.get_doc(SUBMISSION_DOCTYPE, name)

    validate_submission_owner(doc)
    doc.check_permission("write")

    # Students may edit their own submissions.
    # Only evaluators/admin roles may set the result status.
    roles = frappe.get_roles()

    is_evaluator = any(
        role in roles
        for role in [
            "System Manager",
            "Moderator",
            "Course Creator",
            "Batch Evaluator",
        ]
    )

    if status is not None and not is_evaluator:
        frappe.throw(
            _("Only an evaluator can update submission status"),
            frappe.PermissionError,
        )

    if code is not None:
        if not code.strip():
            frappe.throw(_("Code cannot be empty"))

        doc.code = code

    if status is not None:
        if status not in ["Passed", "Failed"]:
            frappe.throw(_("Status must be Passed or Failed"))

        doc.status = status

    if test_cases is not None:
        test_cases = parse_test_cases(test_cases)
        doc.set("test_cases", test_cases)

    doc.save()

    return {
        "status": "success",
        "message": "Submission updated successfully",
        "data": get_submission_response(doc),
    }


# --------------------------------------------------
# DELETE SUBMISSION
# --------------------------------------------------

@frappe.whitelist()
def delete_programming_exercise_submission(name):
    """Delete a programming exercise submission."""

    doc = frappe.get_doc(SUBMISSION_DOCTYPE, name)

    validate_submission_owner(doc)
    doc.check_permission("delete")

    doc.delete()

    return {
        "status": "success",
        "message": "Programming exercise submission deleted successfully",
        "name": name,
    }


# --------------------------------------------------
# SUBMISSION DROPDOWN
# --------------------------------------------------

@frappe.whitelist()
def get_programming_exercise_submission_dropdown(
    exercise=None,
    status=None,
    txt=None,
    limit=50,
):
    """Return accessible submissions for a dropdown."""

    limit = min(100, max(1, int(limit)))

    roles = frappe.get_roles()

    is_privileged = any(
        role in roles
        for role in [
            "System Manager",
            "Moderator",
            "Course Creator",
            "Batch Evaluator",
        ]
    )

    filters = {}

    if not is_privileged:
        if "LMS Student" not in roles:
            frappe.throw(
                _("You do not have permission to view submissions"),
                frappe.PermissionError,
            )

        filters["member"] = frappe.session.user

    if exercise:
        filters["exercise"] = exercise

    if status:
        if status not in ["Passed", "Failed"]:
            frappe.throw(_("Invalid submission status"))

        filters["status"] = status

    if txt:
        filters["name"] = ["like", f"%{txt}%"]

    return frappe.get_list(
        SUBMISSION_DOCTYPE,
        filters=filters,
        fields=[
            "name",
            "exercise",
            "exercise_title",
            "member",
            "member_name",
            "status",
        ],
        order_by="creation desc",
        page_length=limit,
    )