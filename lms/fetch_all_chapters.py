import frappe

def run():
    chapters = frappe.get_all('Course Chapter', fields=['name', 'title', 'course'])
    print(f"Total Chapters: {len(chapters)}")
    for ch in chapters:
        print(f"{ch.name} - {ch.title} (Course: {ch.course})")
        lessons = frappe.get_all('Course Lesson', filters={'chapter': ch.name}, fields=['name', 'title'])
        for less in lessons:
            print(f"  - {less.name} / {less.title}")
