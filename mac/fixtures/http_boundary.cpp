// Exercise the pinned HTTP parser without a model, tokenizer or GPU runtime.
#include "app/server/http.h"
#include "engine/framework/io/json.h"
#include <atomic>
#include <istream>
#include <iterator>
#include <string>

// Error text is not under test; avoid linking the model runtime for JSON quoting.
namespace engine::io::json {
std::string stringify_string(std::string_view) { return "\"fixture\""; }
}

class Handler final : public minitts::server::IHttpHandler {
    std::atomic<unsigned> calls{0};
public:
    minitts::server::HttpResponse handle(const minitts::server::HttpRequest & request) override {
        if (request.path == "/health") return minitts::server::json_response(std::to_string(calls.load()));
        ++calls;
        std::string body = request.body;
        if (request.body_stream) {
            body.assign(std::istreambuf_iterator<char>(*request.body_stream), std::istreambuf_iterator<char>());
        }
        return minitts::server::json_response(std::to_string(body.size()));
    }
};

int main(int argc, char ** argv) {
    if (argc != 2) return 2;
    Handler handler;
    minitts::server::serve_http("127.0.0.1", std::stoi(argv[1]), handler, [] { return false; }, 1024 * 1024);
}
