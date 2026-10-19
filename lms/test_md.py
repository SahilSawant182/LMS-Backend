import frappe

def run():
    doc = frappe.get_meta('Course Lesson')
    for f in doc.fields:
        if f.fieldname == 'body':
            print(f"Body fieldtype: {f.fieldtype}")
            break

    try:
        from frappe.utils import md_to_html
        html = md_to_html("## Hello\n\n**World**")
        print("md_to_html works:")
        print(html)
    except Exception as e:
        print("md_to_html error:", e)
