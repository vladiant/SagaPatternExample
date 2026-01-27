# Saga Pattern Microservices Example with Apache Kafka

This is a complete implementation of the Saga pattern using Python microservices orchestrated with Docker Compose. It demonstrates distributed transaction management with compensating transactions, using Apache Kafka for event-driven asynchronous communication.

## Architecture

The system consists of 4 microservices that handle an order processing workflow:

1. **Order Service** (Port 8001) - Orchestrates the saga
2. **Inventory Service** (Port 8002) - Manages product inventory
3. **Payment Service** (Port 8003) - Processes payments
4. **Delivery Service** (Port 8004) - Schedules deliveries

All services communicate asynchronously via **Apache Kafka** using choreography-based event-driven architecture.

### Messaging Infrastructure

- **Kafka Broker**: Single node Kafka cluster with Zookeeper
- **Topics**: Each event type has its own Kafka topic
- **Consumer Groups**: Each service maintains its own consumer group for fault tolerance
- **Message Format**: JSON-serialized event data

## Saga Flow

### Success Path:
1. Order created → `inventory.reserve` event published
2. Inventory reserved → `payment.process` event published
3. Payment completed → `delivery.schedule` event published
4. Delivery scheduled → **Order marked completed**

### Failure & Compensation:
- If payment fails → `inventory.release` compensation event
- If delivery fails → `payment.refund` + `inventory.release` compensation events

## Project Structure

```
kafka/
├── docker-compose.yml
├── README.md
├── order-service/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app.py
├── inventory-service/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app.py
├── payment-service/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app.py
└── delivery-service/
    ├── Dockerfile
    ├── requirements.txt
    └── app.py
```

## Setup Instructions

### Prerequisites
- Docker and Docker Compose installed
- Sufficient disk space for Kafka/Zookeeper containers (~2GB)

### Startup

```bash
# Start all services
docker-compose up --build

# Or run in detached mode
docker-compose up -d --build
```

### Verification

```bash
# Check all containers
docker-compose ps

# Verify Kafka is healthy
docker-compose exec kafka kafka-broker-api-versions --bootstrap-server localhost:9092

# List all Kafka topics
docker-compose exec kafka kafka-topics --list --bootstrap-server localhost:9092
```

Expected topics:
- `inventory.reserve`, `inventory.reserved`, `inventory.failed`, `inventory.release`, `inventory.released`
- `payment.process`, `payment.completed`, `payment.failed`, `payment.refund`, `payment.refunded`
- `delivery.schedule`, `delivery.scheduled`, `delivery.failed`

## Testing the Saga

### Create a successful order:
```bash
curl -X POST http://localhost:8001/orders \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user_123",
    "product_id": "product_1",
    "quantity": 2,
    "amount": 199.99
  }'
```

Response:
```json
{
  "order_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending"
}
```

### Check order status:
```bash
curl http://localhost:8001/orders/550e8400-e29b-41d4-a716-446655440000
```

### Check system state:
```bash
# View inventory and reservations
curl http://localhost:8002/inventory

# View payment records
curl http://localhost:8003/payments

# View delivery schedules
curl http://localhost:8004/deliveries
```

### Test failure scenarios:

**Insufficient inventory** - triggers inventory.failed event:
```bash
curl -X POST http://localhost:8001/orders \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user_insufficient",
    "product_id": "product_3",
    "quantity": 100,
    "amount": 4999.99
  }'
```

**Payment failure** (20% chance random) - triggers compensation:
```bash
# Run multiple times to hit the 20% failure rate
for i in {1..5}; do
  curl -X POST http://localhost:8001/orders \
    -H "Content-Type: application/json" \
    -d "{\"user_id\": \"user_$i\", \"product_id\": \"product_1\", \"quantity\": 1, \"amount\": 99.99}"
done
```

## Monitoring

### View Kafka Events in Real-time

```bash
# Watch inventory reservation events
docker-compose exec kafka kafka-console-consumer \
  --topic inventory.reserve \
  --from-beginning \
  --bootstrap-server localhost:9092

# Watch payment processing
docker-compose exec kafka kafka-console-consumer \
  --topic payment.process \
  --from-beginning \
  --bootstrap-server localhost:9092

# Watch all events on a topic
docker-compose exec kafka kafka-console-consumer \
  --topic inventory.reserved \
  --from-beginning \
  --bootstrap-server localhost:9092
```

### View Service Logs:
```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f order-service
docker-compose logs -f inventory-service
docker-compose logs -f payment-service
docker-compose logs -f delivery-service

# Follow logs with timestamps
docker-compose logs -f --timestamps
```

### Check Topic Details:
```bash
# List all topics
docker-compose exec kafka kafka-topics --list --bootstrap-server localhost:9092

# Describe a specific topic
docker-compose exec kafka kafka-topics --describe \
  --topic inventory.reserve \
  --bootstrap-server localhost:9092

# Get consumer group information
docker-compose exec kafka kafka-consumer-groups --list \
  --bootstrap-server localhost:9092

# Describe consumer group
docker-compose exec kafka kafka-consumer-groups --describe \
  --group order-service-group \
  --bootstrap-server localhost:9092
```

## Event Flow Examples

### Successful Transaction:
```
ORDER CREATED
    ↓
[Order Service] publishes → inventory.reserve
    ↓
[Inventory Service] reserves → publishes inventory.reserved
    ↓
[Order Service] receives → publishes payment.process
    ↓
[Payment Service] processes → publishes payment.completed
    ↓
[Order Service] receives → publishes delivery.schedule
    ↓
[Delivery Service] schedules → publishes delivery.scheduled
    ↓
[Order Service] receives → ORDER COMPLETED ✓
```

### Payment Failure with Compensation:
```
ORDER CREATED
    ↓
[Inventory Service] reserves → publishes inventory.reserved
    ↓
[Payment Service] fails (20% chance) → publishes payment.failed
    ↓
[Order Service] receives → publishes inventory.release
    ↓
[Inventory Service] releases inventory → publishes inventory.released
    ↓
[Order Service] receives → ORDER FAILED (compensation complete) ✗
```

### Delivery Failure with Full Compensation:
```
[Delivery Service] fails → publishes delivery.failed
    ↓
[Order Service] receives → publishes payment.refund + inventory.release
    ↓
[Payment Service] refunds → publishes payment.refunded
[Inventory Service] releases → publishes inventory.released
    ↓
[Order Service] receives both → ORDER FAILED (full compensation) ✗
```

## Kafka vs RabbitMQ

This implementation was migrated from RabbitMQ to Apache Kafka. Key differences:

| Feature | RabbitMQ | Kafka |
|---------|----------|-------|
| Message Broker | Queue-based | Distributed event log |
| Scalability | Vertical | Horizontal |
| Throughput | ~50K msg/sec | 1M+ msg/sec |
| Consumer Groups | Not built-in | Native support |
| Message Retention | Transient | Persistent |
| Topic Replication | No | Yes |
| Use Case | Traditional queuing | Event streaming |

## Key Features

- **Choreography-based Saga**: Each service listens to events and publishes new events without central coordinator
- **Compensating Transactions**: Automatic rollback on failures with event-driven compensation
- **Event-Driven**: Asynchronous communication via Apache Kafka topics
- **Consumer Groups**: Each service uses dedicated consumer groups for horizontal scalability
- **Topic-based Routing**: Events routed via topic names instead of exchanges
- **Idempotency**: Services can handle duplicate message consumption
- **State Tracking**: Order service maintains saga state and event history
- **Fault Tolerance**: Failed messages are retained in Kafka for debugging and replay

## Known Limitations

- Single-node Kafka cluster (suitable for development/testing)
- In-memory state storage (data lost on container restart)
- No distributed tracing or correlation IDs
- No retry logic with exponential backoff
- No timeout handling for stuck sagas
- Consumer threads may require adjustment for high-concurrency scenarios

## Cleanup

```bash
# Stop all services
docker-compose down

# Stop and remove volumes (clears all data)
docker-compose down -v

# Remove images
docker rmi kafka_order-service kafka_inventory-service \
           kafka_payment-service kafka_delivery-service
```

## Extending the Example

To add production-ready features:

### 1. Resilience
   - Add timeout handling for long-running operations
   - Implement retry logic with exponential backoff
   - Add circuit breakers for service failures

### 2. Observability
   - Integrate distributed tracing (OpenTelemetry)
   - Add correlation IDs to event chains
   - Implement comprehensive logging and metrics

### 3. Persistence
   - Persist saga state to PostgreSQL/MongoDB
   - Store event log for audit trail
   - Implement event sourcing pattern

### 4. Scaling
   - Deploy multi-node Kafka cluster with replication
   - Add consumer group rebalancing
   - Implement partition key strategy for ordering

### 5. Architecture
   - Implement orchestration-based saga with coordinator
   - Add saga timeout and dead-letter queues
   - Support for compensating transaction rollbacks

## Architecture Comparison

### Current (Choreography-based)
```
Service A → Event → Service B → Event → Service C
↑                                           ↓
←――――――――― Compensation Events ―――――――――――
```

### Alternative (Orchestration-based)
```
Service A ⟷ Saga Orchestrator ⟷ Service B
Service C ⟷ Saga Orchestrator ⟷ Service D
```

## Testing Notes

- Events are successfully published to Kafka topics
- Services can be tested independently via REST APIs
- Kafka persists all messages for debugging and replay
- Consumer threads may take 10-15 seconds to fully initialize on first startup
- Flask debug mode with volume mounts allows rapid development and testing

## References

- [Apache Kafka Documentation](https://kafka.apache.org/documentation/)
- [Saga Pattern](https://microservices.io/patterns/data/saga.html)
- [Choreography vs Orchestration](https://docs.microsoft.com/en-us/azure/architecture/patterns/saga)
- [Event-driven architecture](https://www.confluent.io/blog/event-driven-microservices/)

## License

MIT
