import os
import json
import time
import random
from kafka import KafkaProducer, KafkaConsumer
from flask import Flask, jsonify

app = Flask(__name__)

# In-memory delivery tracking
deliveries = {}

# Kafka connection settings
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")

# Create Kafka producer with relaxed timeouts
producer = KafkaProducer(
    bootstrap_servers=[KAFKA_BOOTSTRAP_SERVERS],
    value_serializer=lambda v: json.dumps(v).encode('utf-8'),
    acks='all',
    retries=3,
    request_timeout_ms=30000
)


def publish_event(event_type, data):
    """Publish event to Kafka"""
    try:
        producer.send(event_type, value=data)
        producer.flush(timeout=5)
        print(f"Published event: {event_type} - {data}")
    except Exception as e:
        print(f"Error publishing event: {e}")


def handle_schedule_delivery(message):
    """Handle delivery scheduling request"""
    try:
        event_data = json.loads(message.value.decode('utf-8'))
        order_id = event_data["order_id"]

        print(f"Scheduling delivery for order {order_id}")

        # Simulate delivery scheduling with 10% failure rate
        success = random.random() > 0.1

        if success:
            deliveries[order_id] = {
                "status": "scheduled",
                "tracking_number": f"TRK{order_id[:8].upper()}",
                "estimated_delivery": "3-5 business days",
            }

            publish_event(
                "delivery.scheduled",
                {
                    "order_id": order_id,
                    "tracking_number": deliveries[order_id]["tracking_number"],
                },
            )
        else:
            publish_event(
                "delivery.failed",
                {"order_id": order_id, "error": "No delivery slots available"},
            )
    except Exception as e:
        print(f"Error scheduling delivery: {e}")


def start_consumer():
    time.sleep(5)

    try:
        consumer = KafkaConsumer(
            "delivery.schedule",
            bootstrap_servers=[KAFKA_BOOTSTRAP_SERVERS],
            group_id='delivery-service-group',
            auto_offset_reset='earliest',
            value_deserializer=lambda m: m.decode('utf-8'),
            enable_auto_commit=True,
            session_timeout_ms=30000,
            heartbeat_interval_ms=10000
        )

        print("Delivery Service: Started consuming messages")
        for message in consumer:
            handle_schedule_delivery(message)
    except Exception as e:
        print(f"Consumer error: {e}")
        import traceback
        traceback.print_exc()


@app.route("/deliveries", methods=["GET"])
def get_deliveries():
    return jsonify({"deliveries": deliveries}), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy"}), 200


if __name__ == "__main__":
    from threading import Thread

    consumer_thread = Thread(target=start_consumer, daemon=True)
    consumer_thread.start()

    app.run(host="0.0.0.0", port=8000, debug=True, use_reloader=False)
