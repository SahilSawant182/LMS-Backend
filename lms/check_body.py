import frappe

def run():
    doc = frappe.get_doc('Course Lesson', frappe.get_all('Course Lesson', filters={'title': 'What is Cloud Computing?'}, limit=1)[0].name)
    print(repr(doc.body))
