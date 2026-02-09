# Minecraft Java Edition Server Dockerfile
# 基于官方 itzg/minecraft-server 镜像的自定义配置

FROM itzg/minecraft-server:latest

# 设置默认环境变量
ENV EULA=TRUE \
    TYPE=VANILLA \
    VERSION=LATEST \
    MEMORY=2G \
    MAX_PLAYERS=20 \
    DIFFICULTY=normal \
    MODE=survival \
    MOTD="Managed by Game Server Manager" \
    ENABLE_RCON=true \
    RCON_PORT=25575 \
    RCON_PASSWORD=minecraft

# 暴露游戏端口和 RCON 端口
EXPOSE 25565 25575

# 数据卷挂载点
VOLUME ["/data"]
