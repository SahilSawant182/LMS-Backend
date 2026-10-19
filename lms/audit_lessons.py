import frappe

def run():
    courses = frappe.get_all('LMS Course', fields=['name', 'title'])
    print(f"Total courses: {len(courses)}")
    for course in courses:
        print(f"\n{'='*60}")
        print(f"Course: {course.name} | {course.title}")
        chapters = frappe.get_all('Course Chapter', filters={'course': course.name}, fields=['name', 'title', 'idx'], order_by='idx asc')
        print(f"  Chapters: {len(chapters)}")
        for ch in chapters:
            lessons = frappe.get_all('Course Lesson', filters={'chapter': ch.name}, fields=['name', 'title', 'body'], order_by='idx asc')
            print(f"  Chapter [{ch.idx}]: {ch.title} | Lessons: {len(lessons)}")
            for les in lessons:
                has_body = 'YES' if les.body and len(les.body.strip()) > 20 else 'EMPTY'
                print(f"    Lesson: {les.title} | Body: {has_body} ({len(les.body or '')} chars)")
