.PHONY: setup run docker-build docker-run docker-clean

setup:
	python3 -m venv venv
	. venv/bin/activate && pip3 install -r requirements.txt

run:
	. venv/bin/activate && python3 main.py

docker-clean:
	docker stop blogautomation || true
	docker rm blogautomation || true
	docker rmi blogautomation || true

docker-build: docker-clean
	docker build -t blogautomation .

docker-run: docker-build
	docker run blogautomation
docker-logs:
	docker logs -f blogautomation
