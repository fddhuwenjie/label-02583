# Terraria Server Dockerfile
# 基于官方 ryshe/terraria 镜像

FROM ryshe/terraria:latest

# 设置默认环境变量
ENV WORLD_FILENAME=world.wld \
    WORLD_SIZE=2 \
    MAX_PLAYERS=8 \
    DIFFICULTY=0 \
    MOTD="Managed by Game Server Manager"

# 暴露游戏端口
EXPOSE 7777

# 数据卷挂载点
VOLUME ["/root/.local/share/Terraria/Worlds"]
