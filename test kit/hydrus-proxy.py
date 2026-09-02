from flask import Flask, Response
import requests

API_KEY = "99adfca3533b407b76a8bdc7ba0043b94e17a383b7d5bac06811cd9e6a0bc705"
HYDRUS_URL = "http://127.0.0.1:45869"

app = Flask(__name__)

@app.route("/video/<file_id>")
def stream_video(file_id):
    response = requests.get(
        f"{HYDRUS_URL}/get_files/file",
        headers={
            "Hydrus-Client-API-Access-Key": API_KEY
        },
        params={
            "file_id": file_id
        },
        stream=True
    )

    return Response(
        response.iter_content(chunk_size=64 * 1024),
        content_type=response.headers.get(
            "Content-Type",
            "application/octet-stream"
        ),
    )

app.run(port=8080)