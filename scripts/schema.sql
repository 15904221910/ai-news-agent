-- 每日 AI 新闻助手 Agent — SQLite 建表 SQL
-- 由 SQLAlchemy 模型（server/*/models.py）编译生成，与服务启动时 init_db() 的 create_all 一致。
-- 重新生成：python scripts/export_schema.py
-- 说明：APScheduler 作业表（apscheduler_jobs）由 SQLAlchemyJobStore 首次启动时自动创建，未包含在本文件。

CREATE TABLE users (
	id INTEGER NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	email VARCHAR(200), 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);

CREATE TABLE agent_runs (
	id VARCHAR(32) NOT NULL, 
	user_id INTEGER NOT NULL, 
	trigger_type VARCHAR(10) NOT NULL, 
	status VARCHAR(10) NOT NULL, 
	steps_used INTEGER NOT NULL, 
	error TEXT, 
	started_at DATETIME NOT NULL, 
	finished_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
);

CREATE TABLE preferences (
	user_id INTEGER NOT NULL, 
	topics TEXT NOT NULL, 
	keywords TEXT NOT NULL, 
	exclude_keywords TEXT NOT NULL, 
	push_time VARCHAR(5) NOT NULL, 
	push_channels TEXT NOT NULL, 
	channel_urls TEXT NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (user_id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

CREATE TABLE briefs (
	id INTEGER NOT NULL, 
	user_id INTEGER NOT NULL, 
	run_id VARCHAR(32), 
	title VARCHAR(200) NOT NULL, 
	brief_date DATE NOT NULL, 
	content_md TEXT NOT NULL, 
	file_path VARCHAR(300), 
	pushed_at DATETIME, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(run_id) REFERENCES agent_runs (id)
);

CREATE TABLE context_windows (
	id INTEGER NOT NULL, 
	run_id VARCHAR(32) NOT NULL, 
	window_index INTEGER NOT NULL, 
	notes TEXT NOT NULL, 
	messages_json TEXT, 
	message_count INTEGER, 
	token_used INTEGER, 
	close_reason VARCHAR(12), 
	opened_at DATETIME NOT NULL, 
	closed_at DATETIME, 
	PRIMARY KEY (id), 
	UNIQUE (run_id, window_index), 
	FOREIGN KEY(run_id) REFERENCES agent_runs (id) ON DELETE CASCADE
);

CREATE TABLE tool_calls (
	id INTEGER NOT NULL, 
	run_id VARCHAR(32) NOT NULL, 
	step INTEGER NOT NULL, 
	window_index INTEGER NOT NULL, 
	thought TEXT, 
	tool_name VARCHAR(50) NOT NULL, 
	tool_args TEXT NOT NULL, 
	tool_result TEXT, 
	is_error INTEGER NOT NULL, 
	duration_ms INTEGER, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(run_id) REFERENCES agent_runs (id) ON DELETE CASCADE
);
