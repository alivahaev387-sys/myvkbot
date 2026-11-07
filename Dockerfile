FROM golang:1.22-alpine AS builder
WORKDIR /src
COPY go.mod ./
COPY . .
RUN go mod tidy
RUN CGO_ENABLED=0 GOOS=linux go build -o /bot .

FROM alpine:latest
RUN apk --no-cache add ca-certificates tzdata
COPY --from=builder /bot /bot
CMD ["/bot"]
