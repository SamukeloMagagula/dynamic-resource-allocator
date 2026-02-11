# --------------------------------------------------------------
# Dynamic Resource Allocation – FINAL DEBUGGED
# --------------------------------------------------------------
import streamlit as st
import boto3
import paramiko
import pandas as pd
import time
from datetime import datetime
import json

# ------------------------------------------------------------------
# 1. CONFIG & DESIGN
# ------------------------------------------------------------------
st.set_page_config(page_title="Dynamic Resource Allocation", page_icon="Cloud", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
<style>
    .main {background-color: #0f172a; color: #e2e8f0;}
    .stApp {font-family: 'Inter', 'Segoe UI', sans-serif;}
    h1, h2, h3 {color: #60a5fa; font-weight: 600;}
    .metric-card {
        background: #1e293b; border-radius: 12px; padding: 1.3rem;
        text-align: center; box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        border: 1px solid #334155;
    }
    .metric-card h3 {font-size: 2rem; margin: 0; color: #60a5fa;}
    .metric-card p {margin: 0.3rem 0 0; font-size: 0.95rem; color: #94a3b8;}
    .stButton>button {
        background: #2563eb; color: white; border: none; border-radius: 10px;
        font-weight: 500; padding: 0.7rem 1.2rem; width: 100%;
        font-size: 1rem; transition: all 0.2s;
    }
    .stButton>button:hover {background: #3b82f6; transform: translateY(-1px);}
    .danger-button>button {background: #dc2626;}
    .danger-button>button:hover {background: #ef4444;}
    .secondary-button>button {background: #475569;}
    .secondary-button>button:hover {background: #64748b;}
    .primary-button>button {background: #7c3aed;}
    .primary-button>button:hover {background: #8b5cf6;}
    .sidebar .css-1d391kg {padding: 1.5rem;}
    .section-header {
        background: #1e40af; color: white; padding: 0.9rem; border-radius: 10px;
        font-weight: 600; margin: 1.8rem 0 1rem; font-size: 1.1rem;
    }
</style>
""", unsafe_allow_html=True)

REGION = "eu-north-1"
ASG_NAME = "my-dynamic-asg"
USERNAME = "ubuntu"
SNS_TOPIC_ARN = "arn:aws:sns:eu-north-1:198852397946:ASGAlerts"
QUEUE_URL = "https://sqs.eu-north-1.amazonaws.com/198852397946/cpu-task-queue"
GUI_IP = "13.60.221.26"
LAMBDA_FUNCTION_NAME = "DynamicAllocator"

ec2 = boto3.client("ec2", region_name=REGION)
autoscaling = boto3.client("autoscaling", region_name=REGION)
sns = boto3.client('sns', region_name=REGION)
sqs = boto3.client('sqs', region_name=REGION)
lambda_client = boto3.client('lambda', region_name=REGION)

# ------------------------------------------------------------------
# 2. LOGIN
# ------------------------------------------------------------------
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if not st.session_state.authenticated:
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("<h2 style='text-align:center; color:#60a5fa;'>Cloud Secure Access</h2>", unsafe_allow_html=True)
        pwd = st.text_input("Password", type="password", label_visibility="collapsed")
        if st.button("Enter System", use_container_width=True):
            if pwd == "industrial2025":
                st.session_state.authenticated = True
                st.success("Access Granted")
                time.sleep(1)
                st.rerun()
            else:
                st.error("Invalid Password")
    st.stop()

st.markdown("<h1 style='text-align:center;'>Cloud Dynamic Resource Allocation</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align:center; color:#94a3b8;'>Enterprise Auto-Scaling & Task Orchestration Platform</p>", unsafe_allow_html=True)

# ------------------------------------------------------------------
# 3. AUTO-REFRESH
# ------------------------------------------------------------------
if "last_refresh" not in st.session_state:
    st.session_state.last_refresh = time.time()
if time.time() - st.session_state.last_refresh > 30:
    st.session_state.last_refresh = time.time()
    st.rerun()

# ------------------------------------------------------------------
# 4. CORE FUNCTIONS
# ------------------------------------------------------------------
@st.cache_data(ttl=30)
def get_asg_info():
    try:
        resp = autoscaling.describe_auto_scaling_groups(AutoScalingGroupNames=[ASG_NAME])["AutoScalingGroups"][0]
        instances = resp["Instances"]
        running = len([i for i in instances if i["LifecycleState"] == "InService"])
        return {
            "Desired": resp["DesiredCapacity"],
            "Min": resp["MinSize"],
            "Max": resp["MaxSize"],
            "Running": running,
            "Instances": instances
        }
    except Exception as e:
        st.error(f"ASG Error: {e}")
        return {"Desired": 0, "Min": 0, "Max": 0, "Running": 0, "Instances": []}

@st.cache_data(ttl=30)
def get_instance_info():
    try:
        asg = get_asg_info()
        ids = [i["InstanceId"] for i in asg["Instances"]]
        if not ids: return []
        resp = ec2.describe_instances(InstanceIds=ids)
        rows = []
        for res in resp["Reservations"]:
            for inst in res["Instances"]:
                ip = inst.get("PublicIpAddress", "N/A")
                state = inst["State"]["Name"]
                rows.append({"ID": inst["InstanceId"], "IP": ip, "Status": state.capitalize()})
        return rows
    except: return []

def ensure_sqs_queue():
    try:
        sqs.get_queue_attributes(QueueUrl=QUEUE_URL, AttributeNames=['QueueArn'])
        return True
    except sqs.exceptions.QueueDoesNotExist:
        try:
            sqs.create_queue(QueueName="cpu-task-queue")
            st.success("Created SQS queue!")
            return True
        except Exception as e:
            st.error(f"Failed to create SQS queue: {e}")
            return False
    except Exception as e:
        st.warning(f"SQS check failed: {e}")
        return False

def run_stress(ip, cores=8, duration=300):
    if ip == "N/A" or ip == GUI_IP: return "Skipped"
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(ip, username=USERNAME, timeout=10)
        ssh.exec_command("sudo apt update -qq && sudo apt install stress-ng -y -qq || true")
        time.sleep(2)
        ssh.exec_command(f"nohup stress-ng --cpu {cores} --timeout {duration} > /dev/null 2>&1 &")
        ssh.close()
        sns.publish(TopicArn=SNS_TOPIC_ARN, Message=f"Stress started on {ip}", Subject="Stress Test")
        add_feedback(f"Stress started on {ip}", "success")
        return "Running"
    except Exception as e:
        add_feedback(f"Stress failed on {ip}: {str(e)[:30]}", "error")
        return f"Failed: {str(e)[:30]}"

def stop_stress(ip):
    if ip == "N/A" or ip == GUI_IP: return "Skipped"
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(ip, username=USERNAME, timeout=10)
        ssh.exec_command("pkill -f stress-ng || true")
        ssh.close()
        add_feedback(f"Stress stopped on {ip}", "success")
        return "Stopped"
    except Exception as e:
        add_feedback(f"Stop stress failed: {str(e)[:30]}", "error")
        return "Failed"

def publish_tasks(count=10):
    if not ensure_sqs_queue(): return "SQS missing"
    try:
        for _ in range(count):
            sqs.send_message(QueueUrl=QUEUE_URL, MessageBody=json.dumps({"task": "CPU", "id": f"task-{int(time.time())}"}))
        sns.publish(TopicArn=SNS_TOPIC_ARN, Message=f"{count} tasks published", Subject="Tasks Published")
        add_feedback(f"Published {count} tasks", "success")
        return f"{count} queued"
    except Exception as e:
        add_feedback(f"Task publish failed: {e}", "error")
        return f"Failed: {e}"

def get_backlog():
    if not ensure_sqs_queue(): return 0
    try:
        attr = sqs.get_queue_attributes(QueueUrl=QUEUE_URL, AttributeNames=['ApproximateNumberOfMessages'])
        return int(attr['Attributes'].get('ApproximateNumberOfMessages', 0))
    except: return 0

def scale_asg(desired):
    try:
        current = get_asg_info()["Desired"]
        autoscaling.update_auto_scaling_group(AutoScalingGroupName=ASG_NAME, DesiredCapacity=desired)
        sns.publish(TopicArn=SNS_TOPIC_ARN, Message=f"Scaled {current}→{desired}", Subject="Scale")
        st.cache_data.clear()
        add_feedback(f"Scaled to {desired} instances", "success")
    except Exception as e:
        add_feedback(f"Scale failed: {e}", "error")

def stop_extra_instances():
    instances = get_instance_info()
    gui_instance = None
    workers = []
    for inst in instances:
        if inst["IP"] == GUI_IP:
            gui_instance = inst
        elif inst["Status"].lower() == "running":
            workers.append(inst)
    
    if not workers:
        add_feedback("No extra workers to stop", "info")
        return
    
    try:
        ec2.stop_instances(InstanceIds=[w["ID"] for w in workers])
        for w in workers:
            add_feedback(f"Stopped {w['ID'][:12]}...", "success")
    except Exception as e:
        add_feedback(f"Stop failed: {e}", "error")

def trigger_lambda():
    add_feedback("Triggering scaling engine...", "info")
    try:
        response = lambda_client.invoke(
            FunctionName=LAMBDA_FUNCTION_NAME,
            InvocationType='RequestResponse',
            Payload=json.dumps({})
        )
        result = json.loads(response['Payload'].read().decode())
        action = result.get("body", {})
        if isinstance(action, str):
            action = json.loads(action)
        
        desired = action.get("desired", "N/A")
        running = action.get("running", "N/A")
        backlog = action.get("backlog", "N/A")
        act = action.get("action", "none")

        if act == "up":
 dialing add_feedback(f"Scaled UP → {desired} instances (Backlog: {backlog})", "success")
        elif act == "down":
            add_feedback(f"Scaled DOWN → {desired} instances", "success")
        else:
            add_feedback(f"No action needed (Backlog: {backlog})", "info")
        
        st.cache_data.clear()
        time.sleep(2)
        st.rerun()
        return result
    except Exception as e:
        add_feedback(f"Lambda failed: {str(e)[:50]}", "error")
        return {"error": str(e)}

# ------------------------------------------------------------------
# 5. FEEDBACK SECTION
# ------------------------------------------------------------------
st.markdown('<div class="section-header">Scaling Feedback</div>', unsafe_allow_html=True)
if "scaling_feedback" not in st.session_state:
    st.session_state.scaling_feedback = []

def add_feedback(message, status="info"):
    timestamp = datetime.now().strftime("%H:%M:%S")
    st.session_state.scaling_feedback.append({
        "time": timestamp,
        "message": message,
        "status": status
    })
    if len(st.session_state.scaling_feedback) > 10:
        st.session_state.scaling_feedback.pop(0)

if st.session_state.scaling_feedback:
    for fb in st.session_state.scaling_feedback:
        if fb["status"] == "success":
            st.success(f"[{fb['time']}] {fb['message']}")
        elif fb["status"] == "error":
            st.error(f"[{fb['time']}] {fb['message']}")
        else:
            st.info(f"[{fb['time']}] {fb['message']}")
else:
    st.info("No scaling activity yet.")

# ------------------------------------------------------------------
# 6. DASHBOARD
# ------------------------------------------------------------------
asg = get_asg_info()
instances = get_instance_info()
backlog = get_backlog()

st.markdown('<div class="section-header">Resource Cluster Overview</div>', unsafe_allow_html=True)
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.markdown(f'<div class="metric-card"><h3>{asg["Desired"]}</h3><p>Desired</p></div>', unsafe_allow_html=True)
with col2:
    st.markdown(f'<div class="metric-card"><h3>{asg["Running"]}</h3><p>InService</p></div>', unsafe_allow_html=True)
with col3:
    st.markdown(f'<div class="metric-card"><h3>{backlog}</h3><p>Backlog</p></div>', unsafe_allow_html=True)
with col4:
    st.markdown(f'<div class="metric-card"><h3>$0.50</h3><p>Week</p></div>', unsafe_allow_html=True)

st.markdown("---")
if instances:
    df = pd.DataFrame(instances)
    st.markdown("**Live Nodes**")
    st.dataframe(df, use_container_width=True, hide_index=True)
else:
    st.info("No nodes")

# ------------------------------------------------------------------
# 7. SIDEBAR
# ------------------------------------------------------------------
st.sidebar.markdown("### Cloud Control Center")

with st.sidebar.expander("Stress Testing", expanded=False):
    cores = st.slider("Cores", 1, 16, 8)
    duration = st.slider("Duration (s)", 60, 600, 300, step=30)
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Start Stress", use_container_width=True):
            for inst in instances:
                if inst["IP"] != "N/A" and inst["IP"] != GUI_IP:
                    run_stress(inst["IP"], cores, duration)
    with c2:
        st.markdown('<div class="danger-button">', unsafe_allow_html=True)
        if st.button("Stop Stress", use_container_width=True):
            for inst in instances:
                if inst["IP"] != "N/A" and inst["IP"] != GUI_IP:
                    stop_stress(inst["IP"])
        st.markdown('</div>', unsafe_allow_html=True)

with st.sidebar.expander("Tasks", expanded=False):
    if st.button("Publish 10 Tasks", use_container_width=True):
        result = publish_tasks(10)
        if "Failed" in result:
            st.error(result)
        else:
            st.success(result)

with st.sidebar.expander("Scaling", expanded=False):
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Scale Up +1", use_container_width=True):
            scale_asg(asg["Desired"] + 1)
    with c2:
        st.markdown('<div class="secondary-button">', unsafe_allow_html=True)
        if st.button("Scale Down -1", use_container_width=True) and asg["Desired"] > 1:
            scale_asg(asg["Desired"] - 1)
        st.markdown('</div>', unsafe_allow_html=True)
    
    st.markdown('<div class="primary-button">', unsafe_allow_html=True)
    if st.button("Trigger Scaling Engine", use_container_width=True):
        trigger_lambda()
    st.markdown('</div>', unsafe_allow_html=True)
    
    if st.button("Stop Extra Workers", use_container_width=True):
        stop_extra_instances()

with st.sidebar.expander("Alerts", expanded=False):
    if st.button("Test Email", use_container_width=True):
        try:
            sns.publish(TopicArn=SNS_TOPIC_ARN, Message="Test", Subject="Test")
            add_feedback("Test email sent", "success")
        except Exception as e:
            add_feedback(f"Email failed: {e}", "error")

st.sidebar.markdown("---")
st.sidebar.caption("GUI: http://13.60.221.26:8501")
st.sidebar.caption("Region: eu-north-1")
