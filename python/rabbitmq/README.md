# Saga Pattern Microservices Example

This is a complete implementation of the Saga pattern using Python microservices orchestrated with Docker Compose. It demonstrates distributed transaction management with compensating transactions.

## Architecture

The system consists of 4 microservices that handle an order processing workflow:

1. **Order Service** (Port 8001) - Orchestrates the saga
2. **Inventory Service** (Port 8002) - Manages product inventory
3. **Payment Service** (Port 8003) - Processes payments
4. **Delivery Service** (Port 8004) - Schedules deliveries

All services communicate asynchronously via RabbitMQ using event-driven architecture.

## Saga Flow

### Success Path:
1. Order created → Reserve inventory
2. Inventory reserved → Process payment
3. Payment completed → Schedule delivery
4. Delivery scheduled → **Order completed**

### Failure & Compensation:
- If payment fails → Release reserved inventory
- If delivery fails → Refund payment + Release inventory

## Project Structure

```
saga-pattern/
├── docker-compose.yml
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

1. **Start all services:**
```bash
docker-compose up --build
```

2. **Verify services are running:**
```bash
# Check all containers
docker-compose ps

# Check RabbitMQ Management UI
# Open http://localhost:15672 (admin/admin)
```

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
  "order_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "status": "pending"
}
```

### Check order status:
```bash
curl http://localhost:8001/orders/<order_id>
```

### Check inventory:
```bash
curl http://localhost:8002/inventory
```

### Check payments:
```bash
curl http://localhost:8003/payments
```

### Check deliveries:
```bash
curl http://localhost:8004/deliveries
```

### Test failure scenarios:

**Insufficient inventory:**
```bash
curl -X POST http://localhost:8001/orders \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user_456",
    "product_id": "product_3",
    "quantity": 100,
    "amount": 4999.99
  }'
```

**Payment failure (random 20% chance):**
Just create multiple orders and some will fail at the payment step, triggering inventory compensation.

## Monitoring

### View RabbitMQ exchanges and queues:
1. Open http://localhost:15672
2. Login with `admin/admin`
3. Navigate to "Exchanges" → `saga_events`
4. View message routing and queue bindings

### View service logs:
```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f order-service
docker-compose logs -f payment-service
```

## Event Flow Examples

### Successful Transaction:
```
inventory.reserve → inventory.reserved → 
payment.process → payment.completed → 
delivery.schedule → delivery.scheduled
```

### Payment Failure:
```
inventory.reserve → inventory.reserved → 
payment.process → payment.failed → 
inventory.release → inventory.released
```

### Delivery Failure:
```
inventory.reserve → inventory.reserved → 
payment.process → payment.completed → 
delivery.schedule → delivery.failed → 
payment.refund → payment.refunded →
inventory.release → inventory.released
```

## Key Features

- **Choreography-based Saga**: Each service listens to events and publishes new events
- **Compensating Transactions**: Automatic rollback when steps fail
- **Event-Driven**: Asynchronous communication via RabbitMQ
- **Idempotency**: Services handle duplicate messages gracefully
- **State Tracking**: Order service maintains saga state and history

## Cleanup

```bash
# Stop all services
docker-compose down

# Remove volumes (clears all data)
docker-compose down -v
```

## Extending the Example

To add more complexity, consider:
- Implementing orchestration-based saga with a coordinator service
- Adding timeout handling for long-running operations
- Implementing retry logic with exponential backoff
- Adding distributed tracing (OpenTelemetry)
- Persisting state to databases instead of in-memory storage
- Implementing idempotency keys for exactly-once processing
