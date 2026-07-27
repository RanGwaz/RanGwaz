FROM maven:3.9.9-eclipse-temurin-17 AS build

WORKDIR /workspace
COPY pom.xml ./
RUN mvn -q -DskipTests dependency:go-offline
COPY src ./src
RUN mvn -q -DskipTests package

FROM eclipse-temurin:17-jre-alpine

RUN addgroup -S vibelo && adduser -S vibelo -G vibelo \
    && mkdir -p /app/storage/uploads \
    && chown -R vibelo:vibelo /app
WORKDIR /app
COPY --from=build --chown=vibelo:vibelo /workspace/target/*.jar /app/app.jar

USER vibelo
EXPOSE 8080

HEALTHCHECK --interval=15s --timeout=5s --start-period=45s --retries=5 \
  CMD wget -q -O - http://127.0.0.1:8080/actuator/health | grep -q '"status":"UP"' || exit 1

ENTRYPOINT ["java", "-XX:InitialRAMPercentage=25.0", "-XX:MaxRAMPercentage=60.0", "-XX:MaxMetaspaceSize=192m", "-XX:+ExitOnOutOfMemoryError", "-jar", "/app/app.jar"]
