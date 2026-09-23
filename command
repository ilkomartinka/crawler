ssh -p 20079 jouda@dev.spsejecna.net
ssh -p 20079 -N -L 15673:127.0.0.1:15672 jouda@dev.spsejecna.net


# 1. LOCAL: run from the project directory. Log in with your GitHub username
# and a personal access token (classic) with write:packages access as the password.
docker login ghcr.io -u ilkomartinka
# Build for the VPS architecture (linux/amd64); use linux/arm64 for an ARM VPS.
docker buildx build --platform linux/amd64 --tag ghcr.io/ilkomartinka/crawler:latest --push .

# 2. LOCAL: copy the production Compose file to the VPS.
ssh -p 20079 jouda@dev.spsejecna.net 'mkdir -p /home/jouda/crawler'
scp -P 20079 docker-compose.prod.yml jouda@dev.spsejecna.net:/home/jouda/crawler/docker-compose.yml
ssh -p 20079 jouda@dev.spsejecna.net

# 3. VPS: run after connecting. Use a personal access token (classic) with read:packages access as the password.
cd /home/jouda/crawler
docker login ghcr.io -u ilkomartinka
docker compose pull
# Each app container runs one Python worker process: 20 containers = 20 workers.
docker compose up --scale app=20
# The command above stays in the foreground. Run the following commands in
# another SSH session from /home/jouda/crawler.
docker compose ps app

# 4. VPS: enqueue the initial URL once to begin crawling.
docker compose exec --index 1 app python enqueue.py https://www.idnes.cz/

# Registry authentication: https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry
