FROM golang:1.22 AS builder
WORKDIR /app
COPY go.mod ./
COPY . .
RUN go mod tidy
RUN CGO_ENABLED=1 GOOS=linux go build -o /bot .

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y ca-certificates tzdata
WORKDIR /app
COPY --from=builder /bot /bot
CMD ["/bot"]
