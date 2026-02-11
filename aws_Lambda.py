import json
import boto3
import os
from datetime import datetime
import time

# -------------------------------
# CONFIG
# -------------------------------
ASG_NAME = "my-dynamic-asg"
SQS_QUEUE_URL = "https://sqs.eu-north-1.amazonaws.com/198852397946/cpu-task-queue"
SNS_TOPIC_ARN = "arn:aws:sns:eu-north-1:198852397946:ASGAlerts"
REGION = "eu-north-1"

# Adjustable thresholds
HIGH_BACKLOG_THRESHOLD = 10      # Tasks per instance to scale up
LOW_BACKLOG_THRESHOLD = 2        # Tasks per instance to scale down
COOLDOWN_SECONDS = 60            # 1 minute (was 300) — safe for demo
MAX_INSTANCES = 5
MIN_INSTANCES = 1

# Clients
autoscaling = boto3.client('autoscaling', region_name=REGION)
sqs = boto3.client('sqs', region_name=REGION)
sns = boto3.client('sns', region_name=REGION)
ec2 = boto3.client('ec2', region_name=REGION)

# State file (Lambda is stateless — use DynamoDB or S3 in prod)
# For demo: in-memory (resets on cold start — acceptable)
last_scale_time = 0
last_scale_action = "none"

# -------------------------------
# HELPER: Get current ASG state
# -------------------------------
def get_asg_state():
    try:
        resp = autoscaling.describe_auto_scaling_groups(AutoScalingGroupNames=[ASG_NAME])
        asg = resp['AutoScalingGroups'][0]
        desired = asg['DesiredCapacity']
        running = len([i for i in asg['Instances'] if i['LifecycleState'] == 'InService'])
        return desired, running
    except Exception as e:
        print(f"ERROR getting ASG: {e}")
        return 1, 1  # fallback

# -------------------------------
# HELPER: Get SQS backlog
# -------------------------------
def get_backlog():
    try:
        attr = sqs.get_queue_attributes(
            QueueUrl=SQS_QUEUE_URL,
            AttributeNames=['ApproximateNumberOfMessages', 'ApproximateNumberOfMessagesNotVisible']
        )
        visible = int(attr['Attributes'].get('ApproximateNumberOfMessages', 0))
        in_flight = int(attr['Attributes'].get('ApproximateNumberOfMessagesNotVisible', 0))
        return visible + in_flight
    except Exception as e:
        print(f"ERROR getting SQS: {e}")
        return 0

# -------------------------------
# HELPER: Send SNS email
# -------------------------------
def send_alert(message, subject="Scaling Event"):
    try:
        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Message=message,
            Subject=subject
        )
        print(f"ALERT SENT: {subject}")
    except Exception as e:
        print(f"ALERT FAILED: {e}")

# -------------------------------
# MAIN SCALING LOGIC
# -------------------------------
def lambda_handler(event, context):
    global last_scale_time, last_scale_action

    current_time = time.time()
    desired, running = get_asg_state()
    backlog = get_backlog()
    tasks_per_instance = backlog / max(running, 1)

    print(f"STATE: Desired={desired}, Running={running}, Backlog={backlog}, Tasks/Inst={tasks_per_instance:.1f}")

    # Cooldown check
    if current_time - last_scale_time < COOLDOWN_SECONDS:
        print(f"COOLDOWN: {int(COOLDOWN_SECONDS - (current_time - last_scale_time))}s remaining")
        return {"status": "cooldown"}

    # Scale UP
    if tasks_per_instance > HIGH_BACKLOG_THRESHOLD and desired < MAX_INSTANCES:
        new_capacity = min(desired + 1, MAX_INSTANCES)
        try:
            autoscaling.update_auto_scaling_group(
                AutoScalingGroupName=ASG_NAME,
                DesiredCapacity=new_capacity
            )
            msg = f"SCALED UP: {desired} → {new_capacity}\nBacklog: {backlog} tasks"
            send_alert(msg, "Scale Up")
            last_scale_time = current_time
            last_scale_action = "up"
            print(f"SCALED UP to {new_capacity}")
        except Exception as e:
            send_alert(f"SCALE UP FAILED: {e}", "ERROR")
            print(f"SCALE FAILED: {e}")

    # Scale DOWN
    elif tasks_per_instance < LOW_BACKLOG_THRESHOLD and desired > MIN_INSTANCES:
        new_capacity = max(desired - 1, MIN_INSTANCES)
        try:
            autoscaling.update_auto_scaling_group(
                AutoScalingGroupName=ASG_NAME,
                DesiredCapacity=new_capacity
            )
            msg = f"SCALED DOWN: {desired} → {new_capacity}\nBacklog: {backlog} tasks"
            send_alert(msg, "Scale Down")
            last_scale_time = current_time
            last_scale_action = "down"
            print(f"SCALED DOWN to {new_capacity}")
        except Exception as e:
            send_alert(f"SCALE DOWN FAILED: {e}", "ERROR")
            print(f"SCALE FAILED: {e}")

    else:
        print("NO ACTION: Within thresholds")

    return {
        "statusCode": 200,
        "body": json.dumps({
            "desired": desired,
            "running": running,
            "backlog": backlog,
            "action": last_scale_action
        })
    }
