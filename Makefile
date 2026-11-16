
.PHONY: build clean

build:
	pyinstaller \
		--onefile \
		--name docker-volume-backup \
		--paths src \
		build_entry.py

clean:
	rm -rf build dist *.spec
