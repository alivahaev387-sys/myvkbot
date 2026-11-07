FROM golang:1.22-alpine AS builder
WORKDIR /app
RUN apk add --no-cache gcc musl-dev
COPY go.mod ./
COPY . .
RUN go mod tidy
RUN CGO_ENABLED=1 GOOS=linux go build -o /bot .

FROM alpine:latest
RUN apk --no-cache add ca-certificates tzdata libc6-compat
WORKDIR /app
COPY --from=builder /bot /bot
CMD ["/bot"]
