import frappe

def run():
    doc = frappe.get_meta('Course Lesson')
    for f in doc.fields:
        if f.fieldname in ['body', 'content', 'description']:
            print(f.fieldname, f.fieldtype)
