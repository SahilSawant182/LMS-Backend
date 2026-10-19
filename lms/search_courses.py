import frappe

def run():
    docs = frappe.get_all('LMS Course', fields=['name', 'title'])
    for d in docs:
        print(f"Name: {d.name}, Title: {d.title}")
