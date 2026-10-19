# Copyright (c) 2025, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, nowdate


class LMSCoupon(Document):
	def validate(self):
		self.convert_to_uppercase()
		self.validate_expiry_date()
		self.validate_applicable_items()
		self.validate_usage_limit()

	def convert_to_uppercase(self):
		if self.code:
			self.code = self.code.strip().upper()

	def validate_expiry_date(self):
		if not self.enabled:
			return

		if self.expires_on and str(self.expires_on) < nowdate():
			frappe.throw(_("Expiry date cannot be in the past"))

	def validate_applicable_items(self):
		if not self.get("applicable_items") or len(self.get("applicable_items")) == 0:
			frappe.throw(_("At least one applicable item is required"))

	def validate_usage_limit(self):
		if self.usage_limit is not None and cint(self.usage_limit) < 0:
			frappe.throw(_("Usage limit cannot be negative"))


import json
import frappe
from frappe import _
from frappe.utils import cint, flt, getdate


COUPON_DOCTYPE = "LMS Coupon"

COUPON_FIELDS = {
    "code",
    "enabled",
    "expires_on",
    "discount_type",
    "percentage_discount",
    "fixed_amount_discount",
    "usage_limit",
    "applicable_items",
}


def coupon_request_data():
    data = {}

    if frappe.request and frappe.request.data:
        try:
            body = frappe.request.get_json(silent=True)
            if isinstance(body, dict):
                data.update(body)
        except Exception:
            pass

    data.update(dict(frappe.form_dict))

    # Remove API parameters that are not DocType fields
    for key in ("method", "doctype", "name"):
        data.pop(key, None)

    return data


def parse_coupon_items(items):
    """Parse and validate the applicable-items child table payload."""

    if isinstance(items, str):
        try:
            items = json.loads(items)
        except json.JSONDecodeError:
            frappe.throw(_("Applicable Items must contain valid JSON."))

    if not isinstance(items, list):
        frappe.throw(_("Applicable Items must be a JSON array."))

    for item in items:
        if not isinstance(item, dict):
            frappe.throw(
                _("Each Applicable Item must be a JSON object.")
            )

        # Child-table identity and parent fields are assigned by Frappe.
        forbidden = {"name", "parent", "parenttype", "parentfield"}
        if forbidden.intersection(item):
            frappe.throw(
                _("Do not provide child-table system fields.")
            )

    return items


def validate_coupon_data(data, creating=False):
    """Validate coupon fields and discount configuration."""

    if creating and not data.get("code"):
        frappe.throw(_("Coupon Code is required."))

    if creating and not data.get("discount_type"):
        frappe.throw(_("Discount Type is required."))

    discount_type = data.get("discount_type")

    if discount_type and discount_type not in [
        "Percentage",
        "Fixed Amount",
    ]:
        frappe.throw(
            _("Discount Type must be Percentage or Fixed Amount.")
        )

    if discount_type == "Percentage":
        percentage = data.get("percentage_discount")

        if percentage is None or percentage == "":
            frappe.throw(
                _("Percentage Discount is required.")
            )

        percentage = flt(percentage)

        if percentage <= 0 or percentage > 100:
            frappe.throw(
                _("Percentage Discount must be greater than 0 and at most 100.")
            )

    elif discount_type == "Fixed Amount":
        amount = data.get("fixed_amount_discount")

        if amount is None or amount == "":
            frappe.throw(
                _("Fixed Amount Discount is required.")
            )

        if flt(amount) <= 0:
            frappe.throw(
                _("Fixed Amount Discount must be greater than 0.")
            )

    usage_limit = data.get("usage_limit")

    if usage_limit is not None and usage_limit != "":
        if cint(usage_limit) < 0:
            frappe.throw(
                _("Usage Limit cannot be negative.")
            )

    if data.get("expires_on"):
        try:
            getdate(data["expires_on"])
        except (TypeError, ValueError):
            frappe.throw(
                _("Expires On must be a valid date.")
            )

    if creating:
        items = data.get("applicable_items")

        if items is None:
            frappe.throw(_("Applicable Items is required."))

        if not items:
            frappe.throw(
                _("Add at least one Applicable Item.")
            )


def coupon_response(doc):
    """Format a coupon document for API responses."""

    return {
        "name": doc.name,
        "code": doc.code,
        "enabled": doc.enabled,
        "expires_on": doc.expires_on,
        "discount_type": doc.discount_type,
        "percentage_discount": doc.percentage_discount,
        "fixed_amount_discount": doc.fixed_amount_discount,
        "usage_limit": doc.usage_limit,
        "redemption_count": doc.redemption_count,
        "applicable_items": [
            row.as_dict()
            for row in doc.applicable_items
        ],
        "owner": doc.owner,
        "creation": doc.creation,
        "modified": doc.modified,
    }


@frappe.whitelist(methods=["POST"])
def create_lms_coupon(**kwargs):
    """Create a new LMS Coupon."""

    data = coupon_request_data()
    data.update(kwargs)

    unknown = set(data) - COUPON_FIELDS

    if unknown:
        frappe.throw(
            _("Unsupported fields: {0}").format(
                ", ".join(sorted(unknown))
            )
        )

    items = data.get("applicable_items")

    if items is not None:
        data["applicable_items"] = parse_coupon_items(items)

    validate_coupon_data(data, creating=True)

    doc = frappe.get_doc({
        "doctype": COUPON_DOCTYPE,
        "code": data["code"],
        "enabled": cint(data.get("enabled", 1)),
        "expires_on": data.get("expires_on") or None,
        "discount_type": data["discount_type"],
        "percentage_discount": (
            data.get("percentage_discount")
            if data["discount_type"] == "Percentage"
            else None
        ),
        "fixed_amount_discount": (
            data.get("fixed_amount_discount")
            if data["discount_type"] == "Fixed Amount"
            else None
        ),
        "usage_limit": cint(data.get("usage_limit", 0)),
        "applicable_items": data["applicable_items"],
    })

    doc.insert()

    return {
        "success": True,
        "message": "Coupon created successfully.",
        "data": coupon_response(doc),
    }


@frappe.whitelist(methods=["GET"])
def get_lms_coupon(name):
    """Get one coupon by document name."""

    if not frappe.db.exists(COUPON_DOCTYPE, name):
        frappe.throw(
            _("Coupon {0} does not exist.").format(name),
            frappe.DoesNotExistError,
        )

    doc = frappe.get_doc(COUPON_DOCTYPE, name)
    doc.check_permission("read")

    return {
        "success": True,
        "data": coupon_response(doc),
    }


@frappe.whitelist(methods=["GET"])
def get_lms_coupon_list(
    code=None,
    discount_type=None,
    enabled=None,
    limit_start=0,
    limit_page_length=20,
):
    """Get a filtered, paginated coupon list."""

    filters = {}

    if code:
        filters["code"] = ["like", f"%{code}%"]

    if discount_type:
        filters["discount_type"] = discount_type

    if enabled is not None and enabled != "":
        filters["enabled"] = cint(enabled)

    rows = frappe.get_list(
        COUPON_DOCTYPE,
        filters=filters,
        fields=[
            "name",
            "code",
            "enabled",
            "expires_on",
            "discount_type",
            "percentage_discount",
            "fixed_amount_discount",
            "usage_limit",
            "redemption_count",
            "owner",
            "creation",
            "modified",
        ],
        order_by="creation desc",
        start=max(cint(limit_start), 0),
        page_length=min(max(cint(limit_page_length), 1), 100),
    )

    return {
        "success": True,
        "count": len(rows),
        "data": rows,
    }


@frappe.whitelist(methods=["PUT", "PATCH", "POST"])
def update_lms_coupon(name, **kwargs):
    """Update an existing LMS Coupon."""

    if not frappe.db.exists(COUPON_DOCTYPE, name):
        frappe.throw(
            _("Coupon {0} does not exist.").format(name),
            frappe.DoesNotExistError,
        )

    doc = frappe.get_doc(COUPON_DOCTYPE, name)
    doc.check_permission("write")

    data = coupon_request_data()
    data.update(kwargs)

    data.pop("name", None)
    data.pop("doctype", None)

    unknown = set(data) - COUPON_FIELDS

    if unknown:
        frappe.throw(
            _("Unsupported fields: {0}").format(
                ", ".join(sorted(unknown))
            )
        )

    # Update only fields explicitly supplied by the caller.
    if "code" in data:
        doc.code = data["code"]

    if "enabled" in data:
        doc.enabled = cint(data["enabled"])

    if "expires_on" in data:
        doc.expires_on = data["expires_on"] or None

    if "discount_type" in data:
        doc.discount_type = data["discount_type"]

    if "percentage_discount" in data:
        doc.percentage_discount = data["percentage_discount"]

    if "fixed_amount_discount" in data:
        doc.fixed_amount_discount = data["fixed_amount_discount"]

    if "usage_limit" in data:
        doc.usage_limit = cint(data["usage_limit"])

    if "applicable_items" in data:
        doc.set(
            "applicable_items",
            parse_coupon_items(data["applicable_items"]),
        )

    # Do not allow API clients to edit redemption_count.
    validate_coupon_data({
        "code": doc.code,
        "discount_type": doc.discount_type,
        "percentage_discount": doc.percentage_discount,
        "fixed_amount_discount": doc.fixed_amount_discount,
        "usage_limit": doc.usage_limit,
        "expires_on": doc.expires_on,
    })

    doc.save()

    return {
        "success": True,
        "message": "Coupon updated successfully.",
        "data": coupon_response(doc),
    }


@frappe.whitelist(methods=["DELETE", "POST"])
def delete_lms_coupon(name):
    """Delete an existing coupon."""

    if not frappe.db.exists(COUPON_DOCTYPE, name):
        frappe.throw(
            _("Coupon {0} does not exist.").format(name),
            frappe.DoesNotExistError,
        )

    doc = frappe.get_doc(COUPON_DOCTYPE, name)
    doc.check_permission("delete")

    doc.delete()

    return {
        "success": True,
        "message": "Coupon deleted successfully.",
        "name": name,
    }