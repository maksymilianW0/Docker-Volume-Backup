
.PHONY: build clean

build:
	pyinstaller \
		--onefile \
		--name dvb \
		--paths src \
		build_entry.py

clean:
	rm -rf build dist *.spec
