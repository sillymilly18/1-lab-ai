#include "TaskScheduler.h"
#include <chrono>
#include <iostream>

using namespace std::chrono;

int main()
{
	using namespace std::chrono;
	auto d1 = hours(24);
	auto d2 = hours(48);
	auto d3 = hours(72);
	auto d5 = hours(120);
	auto d7 = hours(168);
	auto now = sys_days{2026y / May / 27d} + 12h + 0min + 0s;

	TaskScheduler<IT_Priority> scheduler(4, now);
	scheduler.add_task("tag-task", "Title task", "Description task", 12 /*duration*/, IT_Priority::Critical /*priority*/, now + d3 /*deadline*/);
	// scheduler.add_task(/*...*/);
	// scheduler.add_task(/*...*/);
	/*...*/
	scheduler.optimize();
	std::cout << "=== OPTIMIZED CALENDAR ===\n";
	std::cout << " = PLANNED = \n";
	operator<< <IT_Priority, false>(std::cout, scheduler);
	std::cout << " = DROPPED = \n";
	operator<< <IT_Priority, true>(std::cout, scheduler);
	std::cout << "\n";
	std::cout << scheduler.export_calendar();
	return 0;
}
