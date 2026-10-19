import frappe


@frappe.whitelist(allow_guest=True)
def get_dropdown_options(
    doctype,
    txt="",
    limit=50,
    filters=None
):
    """
    Generic dropdown API for LMS.

    Example:
    /api/method/lms.lms.master.get_dropdown_options
    ?doctype=LMS%20Course
    """

    try:
        if not doctype:
            return {
                "success": False,
                "message": "DocType is required."
            }

        limit = int(limit or 50)

        if isinstance(filters, str):
            filters = frappe.parse_json(filters)

        filters = filters or {}

        # Check DocType exists
        if not frappe.db.exists("DocType", doctype):
            return {
                "success": False,
                "message": f"{doctype} does not exist."
            }

        meta = frappe.get_meta(doctype)

        fields = ["name"]

        # Possible label fields
        for field in ["title", "course_name", "full_name"]:
            if meta.has_field(field):
                fields.append(field)

        # Search fields
        or_filters = [
            ["name", "like", f"%{txt}%"]
        ]

        for field in ["title", "course_name", "full_name"]:
            if meta.has_field(field):
                or_filters.append(
                    [field, "like", f"%{txt}%"]
                )

        data = frappe.get_list(
            doctype,
            filters=filters,
            fields=fields,
            or_filters=or_filters,
            order_by="modified desc",
            limit_page_length=limit
        )

        options = []

        for row in data:

            label = (
                row.get("title")
                or row.get("course_name")
                or row.get("full_name")
                or row.get("name")
            )

            options.append({
                "value": row.get("name"),
                "label": label
            })

        return {
            "success": True,
            "data": options
        }

    except Exception as e:

        frappe.log_error(
            frappe.get_traceback(),
            "LMS Dropdown API Error"
        )

        return {
            "success": False,
            "message": str(e)
        }