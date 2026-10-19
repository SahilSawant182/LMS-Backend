# Copyright (c) 2023, Frappe and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
def success(data=None, message="Success"):
    return {
        "status": 200,
        "message": message,
        "data": data
    }


def error(message, status=400, data=None):
    frappe.local.response.http_status_code = status
    return {
        "status": status,
        "message": message,
        "data": data
    }

class LMSCategory(Document):
	pass

@frappe.whitelist()
def get_category_list(txt=None, limit_start=0, limit_page_length=20):
    try:
        limit_start = max(0, int(limit_start))
        limit_page_length = min(100, max(1, int(limit_page_length)))

        filters = {}

        if txt:
            filters["category"] = ["like", f"%{txt.strip()}%"]

        categories = frappe.get_all(
            "LMS Category",
            filters=filters,
            fields=[
                "name",
                "category",
                "creation",
                "modified"
            ],
            order_by="modified desc",
            start=limit_start,
            page_length=limit_page_length
        )

        total = frappe.db.count(
            "LMS Category",
            filters=filters
        )

        return success(
            {
                "categories": categories,
                "total": total,
                "limit_start": limit_start,
                "limit_page_length": limit_page_length
            },
            "Categories fetched successfully"
        )

    except Exception as e:
        frappe.log_error(
            frappe.get_traceback(),
            "Get LMS Category List"
        )

        return error(str(e), 500)


@frappe.whitelist()
def create_category(category):
    try:
        # Validate required field
        if not category or not category.strip():
            return error("Category is required", 400)

        category = category.strip()

        # Check duplicate category
        if frappe.db.exists("LMS Category", category):
            return error("Category already exists", 409)

        # Create category
        doc = frappe.get_doc({
            "doctype": "LMS Category",
            "category": category
        })

        doc.insert(ignore_permissions=True)
        frappe.db.commit()

        return success(
            doc.as_dict(),
            "Category created successfully"
        )

    except Exception as e:
        frappe.db.rollback()

        frappe.log_error(
            frappe.get_traceback(),
            "Create LMS Category"
        )

        return error(str(e), 500)




@frappe.whitelist()
def delete_category(name):
    try:
        if not name:
            return error("Category name is required", 400)

        if not frappe.db.exists("LMS Category", name):
            return error("Category not found", 404)

        # Prevent deleting a category used by courses
        if frappe.db.exists(
            "LMS Course",
            {"category": name}
        ):
            return error(
                "Cannot delete category because it is assigned to existing courses",
                409
            )

        frappe.delete_doc(
            "LMS Category",
            name,
            ignore_permissions=True
        )

        frappe.db.commit()

        return success(
            {"name": name},
            "Category deleted successfully"
        )

    except Exception as e:
        frappe.db.rollback()

        frappe.log_error(
            frappe.get_traceback(),
            "Delete LMS Category"
        )

        return error(str(e), 500)