import sys
sys.path.insert(0, '/home/dev/lms-bench/apps/frappe')
import frappe

frappe.init(site='devlms.stridenex.ai', sites_path='/home/dev/lms-bench/sites')
frappe.connect()

def run():
    lessons = frappe.get_all('Course Lesson', fields=['name', 'title', 'course', 'chapter', 'body'])
    missing_count = 0
    total_count = len(lessons)
    print(f"Total lessons: {total_count}")
    
    for l in lessons:
        body = (l.body or "").strip()
        if len(body) < 100:
            missing_count += 1
            print(f"MISSING/SHORT: {l.title} ({len(body)} chars)")
            
    print(f"Total missing or short lessons: {missing_count} / {total_count}")

run()
