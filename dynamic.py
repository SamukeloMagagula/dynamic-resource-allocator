# Filename: dynamic_allocator.py

from flask import Flask, request, jsonify
import random

app = Flask(__name__)

# Example of dynamic resource allocator function
def allocate_resources(task_load):
    """
    Simulate CPU, Memory, Storage allocation based on task_load
    task_load: int (0-100)
    Returns: dict of allocated resources
    """
    cpu = min(max(task_load // 10, 1), 8)  # 1-8 vCPUs
    memory = min(max(task_load * 0.5, 1), 32)  # 1-32 GB
    storage = min(max(task_load * 2, 10), 500)  # 10-500 GB
    return {"cpu": cpu, "memory": memory, "storage": storage}

# Home route
@app.route("/")
def home():
    return "Dynamic Resource Allocator is running!"

# API route to allocate resources
@app.route("/allocate", methods=["POST"])
def allocate():
    try:
        data = request.json
        task_load = data.get("task_load", random.randint(1, 100))
        result = allocate_resources(task_load)
        return jsonify({"status": "success", "task_load": task_load, "allocation": result})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

if __name__ == "__main__":
    # Run Flask app on all IPs, port 80 for EC2
    app.run(host="0.0.0.0", port=80)
