import frappe

def run():
    for dt in ['LMS Course', 'Course Chapter', 'Course Lesson', 'Course Chapter Reference', 'Course Lesson Reference']:
        try:
            fields = frappe.get_meta(dt).fields
            print(f"\nDocType: {dt}")
            for f in fields:
                print(f"  {f.fieldname} ({f.fieldtype})")
        except Exception as e:
            pass
