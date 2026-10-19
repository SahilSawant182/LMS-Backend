import frappe
from frappe.utils import md_to_html

def run():
    doc = frappe.get_doc('Course Lesson', frappe.get_all('Course Lesson', filters={'title': 'What is Cloud Computing?'}, limit=1)[0].name)
    html_content = md_to_html(doc.body)
    doc.body = html_content
    doc.save(ignore_permissions=True)
    frappe.db.commit()
    print("Converted to HTML successfully.")
