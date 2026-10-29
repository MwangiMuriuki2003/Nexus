"""APScheduler-based skill scheduler for Nexus.

Registers skills with cron schedules and executes them at the scheduled time.
Integrates with SkillRegistry to persist and retrieve skill schedule information.
"""

import atexit
import logging
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from Nexus.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)


class SkillScheduler:
    """Scheduler that runs registered skills on a cron schedule."""

    def __init__(self, registry: SkillRegistry | None = None):
        self.registry = registry or SkillRegistry()
        # BackgroundScheduler (not Blocking): the caller keeps running while jobs
        # fire on the scheduler's own thread.
        self.scheduler = BackgroundScheduler()
        # Register shutdown hook
        atexit.register(self.shutdown)

    def start(self) -> None:
        """Start the scheduler, loading all scheduled skills from the registry."""
        logger.info("Starting Skill Scheduler...")
        self._load_and_schedule_skills()
        self.scheduler.start()

    def shutdown(self) -> None:
        """Shut down the scheduler gracefully."""
        logger.info("Shutting down Skill Scheduler...")
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)

    def _load_and_schedule_skills(self) -> None:
        """Load skills with cron_schedule from registry and schedule them."""
        skills = self.registry.list_all()
        for skill in skills:
            cron_schedule = skill.get("cron_schedule")
            skill_name = skill.get("name")
            if cron_schedule and skill_name:
                try:
                    trigger = CronTrigger.from_crontab(cron_schedule)
                    self.scheduler.add_job(
                        self._execute_skill_job,
                        trigger=trigger,
                        args=[skill_name],
                        id=f"skill_{skill_name}",
                        replace_existing=True,
                    )
                    logger.info(f"Scheduled skill '{skill_name}' with cron: {cron_schedule}")
                except Exception as e:
                    logger.warning(f"Failed to schedule skill '{skill_name}' with cron '{cron_schedule}': {e}")

    def _execute_skill_job(self, skill_name: str) -> None:
        """Execute a skill job (called by APScheduler)."""
        from Nexus.skills.executor import SkillExecutor

        try:
            executor = SkillExecutor()
            result = executor.execute(skill_name)

            # Update registry with runtime metrics
            if result.get("status") == "ok":
                runtime = result.get("runtime", 30)
                exit_code = result.get("exit_code", 0)
                self.registry.update_last_run(skill_name, exit_code, runtime)
                logger.info(f"Skill '{skill_name}' executed successfully in {runtime:.2f}s")
            else:
                logger.warning(f"Skill '{skill_name}' failed: {result.get('error', 'unknown error')}")
        except Exception as e:
            logger.error(f"Error executing skill '{skill_name}': {e}")

    def schedule_skill(self, skill_name: str, cron_schedule: str) -> bool:
        """Manually schedule a skill with a cron expression.

        Args:
            skill_name: Name of the skill to schedule
            cron_schedule: Cron expression (e.g., '0 9 * * 1' for Monday 9am)

        Returns:
            True if successfully scheduled
        """
        try:
            trigger = CronTrigger.from_crontab(cron_schedule)
            self.scheduler.add_job(
                self._execute_skill_job,
                trigger=trigger,
                args=[skill_name],
                id=f"skill_{skill_name}",
                replace_existing=True,
            )
            # Persist the cron schedule in the registry
            skill = self.registry.get(skill_name)
            if skill:
                self.registry.conn.execute(
                    "UPDATE skills SET cron_schedule = ? WHERE name = ?",
                    (cron_schedule, skill_name),
                )
                self.registry.conn.commit()
            logger.info(f"Manually scheduled skill '{skill_name}' with cron: {cron_schedule}")
            return True
        except Exception as e:
            logger.error(f"Failed to schedule skill '{skill_name}': {e}")
            return False


# Global scheduler instance for easy access
_scheduler: SkillScheduler | None = None


def get_scheduler() -> SkillScheduler:
    """Get the global SkillScheduler instance, initializing if needed."""
    global _scheduler
    if _scheduler is None:
        _scheduler = SkillScheduler()
    return _scheduler


def start_scheduler() -> None:
    """Start the global skill scheduler."""
    scheduler = get_scheduler()
    scheduler.start()


def shutdown_scheduler() -> None:
    """Shut down the global skill scheduler."""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown()