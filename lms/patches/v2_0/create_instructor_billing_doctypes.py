"""
Patch: Create Instructor Billing Doctypes for Stride LMS
Creates 5 new doctypes for the instructor billing / payout system.
"""
import frappe
from frappe.modules.utils import sync_doctypes


def execute():
    """Run during bench migrate. Creates instructor billing doctypes if missing."""
    _sync_instructor_billing_doctypes()


def _sync_instructor_billing_doctypes():
    """Create / update all 5 instructor billing doctypes via direct DB + sync."""
    import json, os

    base = frappe.get_app_path("lms", "lms", "doctype")

    # Ordered: child tables first, then parents
    doctypes = [
        "lms_instructor_commission_tier",
        "lms_instructor_billing_settings",
        "lms_instructor_payout_sheet_row",
        "lms_instructor_payout_sheet",
        "lms_instructor_billing",
    ]

    for snake in doctypes:
        json_path = os.path.join(base, snake, f"{snake}.json")
        if not os.path.exists(json_path):
            frappe.logger().warning(f"[Instructor Billing Patch] JSON not found: {json_path}")
            continue

        with open(json_path) as f:
            dt_data = json.load(f)

        name = dt_data["name"]

        try:
            # Remove from DB cleanly if it exists (handles orphan state)
            if frappe.db.exists("DocType", name):
                frappe.db.sql("DELETE FROM `tabDocType` WHERE name=%s", name)
                frappe.db.sql("DELETE FROM `tabDocPerm` WHERE parent=%s", name)
                frappe.db.sql("DELETE FROM `tabDocField` WHERE parent=%s", name)
                frappe.db.commit()

            # Re-insert with migrate flags to skip link validation
            frappe.flags.in_migrate = True
            doc = frappe.get_doc(dt_data)
            doc.flags.ignore_permissions = True
            doc.flags.ignore_links = True
            doc.insert(ignore_permissions=True, ignore_links=True)
            frappe.db.commit()
            frappe.logger().info(f"[Instructor Billing Patch] Created DocType: {name}")

        except Exception as e:
            frappe.logger().error(f"[Instructor Billing Patch] Failed {name}: {e}")

    # Sync DB tables for all new doctypes
    _create_db_tables()


def _create_db_tables():
    """Create MariaDB tables for the new doctypes using Frappe's DB layer."""
    from frappe.database.schema import DbTableManager

    doctypes = [
        "LMS Instructor Commission Tier",
        "LMS Instructor Billing Settings",
        "LMS Instructor Payout Sheet Row",
        "LMS Instructor Payout Sheet",
        "LMS Instructor Billing",
    ]

    for dt_name in doctypes:
        try:
            if not frappe.db.exists("DocType", dt_name):
                continue
            meta = frappe.get_meta(dt_name, cached=False)
            # Use Frappe's table manager to create/update the table
            db_manager = DbTableManager(frappe.db)
            db_manager.sync(meta)
            frappe.db.commit()
            frappe.logger().info(f"[Instructor Billing Patch] Synced table: {dt_name}")
        except Exception as e:
            # Table might already exist or schema might need different handling
            frappe.logger().warning(f"[Instructor Billing Patch] Table sync warning for {dt_name}: {e}")
