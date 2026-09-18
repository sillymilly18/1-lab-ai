#pragma once

#include <chrono>
#include <iomanip>
#include <iostream>
#include <optional>
#include <string>
#include <vector>

using namespace std;
// git remote add origin git@github.com:se-c-cpp-prog/se-cpp-26-backlog-live2-sillymilly18.git
enum class IT_Priority
{
	Critical = 0,
	High = 1,
	Medium = 2,
	Low = 3
};

template <typename Priority>

struct Task
{
	std::string tag;

	std::string title;
	std::string description;
	int duration;
	Priority priority;
	std::optional<std::chrono::system_clock::time_point> deadline;
};

template <typename Priority>
class TaskScheduler
{
public:
	static inline constexpr int DAILY_CAPACITY_HOURS = 10;
	static inline constexpr int TASK_TAG_LEN = 20; // 16
	static inline constexpr int TASK_DURATION_LEN = 4;

	TaskScheduler() = default;
	~TaskScheduler() = default;

	TaskScheduler(const TaskScheduler &) = delete;
	TaskScheduler &operator=(const TaskScheduler &) = delete;

	TaskScheduler(TaskScheduler &&) = default;
	TaskScheduler &operator=(TaskScheduler &&) = default;

	TaskScheduler &add_task(const Task<Priority> &task)
	{
		task.tag =
	}

	bool &find_task(const std::string &tag) {}

	TaskScheduler optimize() {}
	TaskScheduler scheduled_tasks() const {}
	TaskScheduler dropped_tasks() const {}
	TaskScheduler export_calendar() const {}

private:
	vector<Task<Priority>> tasks_;
	vector<Task<Priority>> scheduled_;
	vector<Task<Priority>> dropped_;
	std::vector<std::vector<Task<Priority>>> calendar_;
	size_ t horizon_days_;

	std::chrono::system_clock::time_point planning_start_;

	void invalidate_cache()
	{
		scheduled_.clear();
		dropped_.clear();
		calendar_.clear();
	}
	void validate_task(const TaskScheduler<Priority> &task) const
	{
		if (task.tag.size() > 20)
		{
			return false;
		}
		if (task.duration() <= 0)
		{
			return false;
		}
		for (char c : task.duration())
		{
			if (!isgraph(static_cast<unsigned char(c)>))
			{
				return false;
			}
		}
	}
};

void print_time(std::chrono::system_clock::time_point tp, std::ostream &os = std::cout)
{
	auto t = std::chrono::system_clock::to_time_t(tp);
	os << std::put_time(std::localtime(&t), "%d.%m.%Y %H:%M");
}

template <typename Priority, bool is_dropped = false>
std::ostream &operator<<(std::ostream &os, TaskScheduler<Priority> &scheduler)
{
	auto list = is_dropped ? scheduler.dropped_tasks() : scheduler.scheduled_tasks();
	// ...
}
