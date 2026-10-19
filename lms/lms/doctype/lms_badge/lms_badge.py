# Copyright (c) 2024, Frappe and contributors
# For license information, please see license.txt

import json

import frappe
from frappe import _
from frappe.model.document import Document


class LMSBadge(Document):
	def on_update(self):
		if self.event == "Manual Assignment" and self.condition:
			try:
				json.loads(self.condition)
			except ValueError:
				frappe.throw(_("Condition must be in valid JSON format."))
		elif self.condition:
			try:
				compile(self.condition, "<string>", "eval")
			except Exception:
				frappe.throw(_("Condition must be valid python code."))

	def apply(self, doc):
		if self.rule_condition_satisfied(doc):
			award(self, doc.get(self.user_field))

	def rule_condition_satisfied(self, doc):
		doc_before_save = doc.get_doc_before_save()

		if self.event == "New" and doc_before_save is not None:
			return False

		if self.condition:
			return eval_condition(doc, self.condition)

		return False


def award(doc, member):
	if doc.grant_only_once:
		if frappe.db.exists(
			"LMS Badge Assignment",
			{"badge": doc.name, "member": member},
		):
			return

	assignment = frappe.new_doc("LMS Badge Assignment")
	assignment.update(
		{
			"badge": doc.name,
			"member": member,
			"issued_on": frappe.utils.now(),
		}
	)
	# nosemgrep: lms-unjustified-ignore-permissions - award() is not reachable directly by a user
	assignment.save(ignore_permissions=True)
	return assignment.name


def eval_condition(doc, condition):
	return condition and frappe.safe_eval(condition, None, {"doc": doc.as_dict()})


@frappe.whitelist()
def assign_badge(badge_name: str):
	frappe.only_for(["Moderator", "Course Creator", "Batch Evaluator"])
	assignments = []
	badge = frappe.db.get_value(
		"LMS Badge",
		badge_name,
		["name", "event", "reference_doctype", "condition", "user_field"],
		as_dict=True,
	)
	if not badge:
		frappe.throw(_("Badge {0} not found").format(badge_name), frappe.DoesNotExistError)

	if not badge.event == "Manual Assignment":
		return

	fields = ["name"]
	fields.append(badge.user_field)
	docs = frappe.get_all(badge.reference_doctype, filters=json.loads(badge.condition), fields=fields)

	for doc in docs:
		assignment_name = award(badge, doc.get(badge.user_field))
		if assignment_name:
			assignments.append(assignment_name)

	return "success" if assignments else "failed"


def process_badges(doc, state):
	if (
		frappe.flags.in_patch
		or frappe.flags.in_install
		or frappe.flags.in_migrate
		or frappe.flags.in_import
		or frappe.flags.in_setup_wizard
	):
		return

	for d in frappe.cache_manager.get_doctype_map(
		"LMS Badge", doc.doctype, dict(reference_doctype=doc.doctype, enabled=1)
	):
		frappe.get_doc("LMS Badge", d.get("name")).apply(doc)



import frappe
from frappe import _
from frappe.utils import cint


DOCTYPE = "LMS Badge"

ALLOWED_FIELDS = {
    "title",
    "enabled",
    "description",
    "reference_doctype",
    "event",
    "image",
    "grant_only_once",
    "user_field",
    "field_to_check",
    "condition",
}


def validate_badge_data(data, creating=False):
    """Validate badge fields before saving."""

    required_fields = [
        "title",
        "image",
        "reference_doctype",
        "event",
        "condition",
        "description",
        "user_field",
    ]

    if creating:
        missing = [
            field
            for field in required_fields
            if data.get(field) is None or data.get(field) == ""
        ]

        if missing:
            frappe.throw(
                _("Required fields are missing: {0}").format(
                    ", ".join(missing)
                )
            )

    if data.get("event") and data["event"] not in [
        "New",
        "Value Change",
        "Manual Assignment",
    ]:
        frappe.throw(_("Invalid event value."))

    if data.get("reference_doctype"):
        if not frappe.db.exists("DocType", data["reference_doctype"]):
            frappe.throw(_("Reference DocType does not exist."))

    if data.get("user_field"):
        meta = frappe.get_meta(data.get("reference_doctype") or "")
        fieldnames = {field.fieldname for field in meta.fields}

        # User Field should refer to a valid field on the reference DocType.
        if data["user_field"] not in fieldnames:
            frappe.throw(
                _("User Field {0} does not exist in {1}.").format(
                    data["user_field"],
                    data.get("reference_doctype"),
                )
            )

    if data.get("event") == "Value Change" and not data.get("field_to_check"):
        frappe.throw(
            _("Field To Check is required for the Value Change event.")
        )


def get_badge_document(title):
    """Load a badge and check read permission."""

    if not frappe.db.exists(DOCTYPE, title):
        frappe.throw(
            _("Badge {0} does not exist.").format(title),
            frappe.DoesNotExistError,
        )

    doc = frappe.get_doc(DOCTYPE, title)
    doc.check_permission("read")

    return doc


@frappe.whitelist(methods=["POST"])
def create_badge(**kwargs):
    """Create an LMS Badge."""

    data = dict(kwargs)

    validate_badge_data(data, creating=True)

    doc = frappe.get_doc(
        {
            "doctype": DOCTYPE,
            **{
                field: data[field]
                for field in ALLOWED_FIELDS
                if field in data
            },
        }
    )

    doc.insert()

    return {
        "success": True,
        "message": "Badge created successfully.",
        "data": doc.as_dict(),
    }


@frappe.whitelist(methods=["GET"])
def get_badge(title):
    """Get one LMS Badge by its title."""

    doc = get_badge_document(title)

    return {
        "success": True,
        "data": doc.as_dict(),
    }


@frappe.whitelist(methods=["GET"])
def get_badge_list(
    txt=None,
    enabled=None,
    event=None,
    reference_doctype=None,
    limit_start=0,
    limit_page_length=20,
):
    """Get a permission-filtered list of LMS Badges."""

    filters = {}

    if enabled is not None:
        filters["enabled"] = cint(enabled)

    if event:
        filters["event"] = event

    if reference_doctype:
        filters["reference_doctype"] = reference_doctype

    limit_start = max(cint(limit_start), 0)
    limit_page_length = min(max(cint(limit_page_length), 1), 100)

    or_filters = None

    if txt:
        or_filters = [
            ["LMS Badge", "title", "like", f"%{txt}%"],
            ["LMS Badge", "description", "like", f"%{txt}%"],
        ]

    badges = frappe.get_list(
        DOCTYPE,
        filters=filters,
        or_filters=or_filters,
        fields=[
            "name",
            "title",
            "enabled",
            "description",
            "reference_doctype",
            "event",
            "image",
            "grant_only_once",
            "user_field",
            "field_to_check",
            "condition",
        ],
        order_by="creation desc",
        start=limit_start,
        page_length=limit_page_length,
    )

    return {
        "success": True,
        "count": len(badges),
        "data": badges,
    }


@frappe.whitelist(methods=["PUT", "PATCH", "POST"])
def update_badge(title, **kwargs):
    """Update an existing LMS Badge."""

    doc = get_badge_document(title)
    doc.check_permission("write")

    data = dict(kwargs)

    # Never allow the API to change the document identity.
    data.pop("name", None)
    data.pop("doctype", None)

    for field, value in data.items():
        if field not in ALLOWED_FIELDS:
            frappe.throw(
                _("Field {0} cannot be updated through this API.").format(
                    field
                )
            )

        doc.set(field, value)

    validate_badge_data(doc.as_dict())

    doc.save()

    return {
        "success": True,
        "message": "Badge updated successfully.",
        "data": doc.as_dict(),
    }


@frappe.whitelist(methods=["DELETE", "POST"])
def delete_badge(title):
    """Delete an existing LMS Badge."""

    doc = get_badge_document(title)
    doc.check_permission("delete")

    doc.delete()

    return {
        "success": True,
        "message": f"Badge {title} deleted successfully.",
    }