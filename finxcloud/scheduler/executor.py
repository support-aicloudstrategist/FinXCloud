"""Schedule executor for FinXCloud — start/stop EC2 instances via AWS API."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

from finxcloud.scheduler.scheduler import ScheduleManager

log = logging.getLogger(__name__)


class ScheduleExecutor:
    """Execute pending schedule actions (stop/start EC2 instances)."""

    def __init__(self, session: boto3.Session, manager: ScheduleManager | None = None) -> None:
        self.session = session
        self.manager = manager or ScheduleManager()

    def execute_due_actions(self, now: datetime | None = None) -> list[dict]:
        """Check all schedules and execute any actions due at the current time.

        Returns a list of action results with status.
        """
        actions = self.manager.get_due_actions(now)
        results: list[dict] = []

        for action in actions:
            result = self._execute_action(action)
            results.append(result)

        return results

    def stop_instance(self, instance_id: str, region: str) -> dict:
        """Stop an EC2 instance."""
        return self._execute_action({
            "instance_id": instance_id,
            "region": region,
            "action": "stop",
            "schedule_id": None,
        })

    def start_instance(self, instance_id: str, region: str) -> dict:
        """Start an EC2 instance."""
        return self._execute_action({
            "instance_id": instance_id,
            "region": region,
            "action": "start",
            "schedule_id": None,
        })

    def _execute_action(self, action: dict) -> dict:
        instance_id = action["instance_id"]
        region = action["region"]
        act = action["action"]

        try:
            ec2 = self.session.client("ec2", region_name=region)
            if act == "stop":
                response = ec2.stop_instances(InstanceIds=[instance_id])
                state = response["StoppingInstances"][0]["CurrentState"]["Name"]
            elif act == "start":
                response = ec2.start_instances(InstanceIds=[instance_id])
                state = response["StartingInstances"][0]["CurrentState"]["Name"]
            else:
                return {**action, "status": "error", "error": f"Unknown action: {act}"}

            log.info("Executed %s on %s in %s — state: %s", act, instance_id, region, state)
            return {
                **action,
                "status": "ok",
                "instance_state": state,
                "executed_at": datetime.now(timezone.utc).isoformat(),
            }
        except ClientError as e:
            error_msg = e.response["Error"].get("Message", str(e))
            log.error("Failed to %s instance %s: %s", act, instance_id, error_msg)
            return {**action, "status": "error", "error": error_msg}
        except Exception as e:
            log.error("Unexpected error executing %s on %s: %s", act, instance_id, e)
            return {**action, "status": "error", "error": str(e)}
