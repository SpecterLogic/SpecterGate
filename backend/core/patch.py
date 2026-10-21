"""Apply the reviewed dispatcher extension to the pinned upstream source."""
from pathlib import Path
import shutil
import sys

root = Path(sys.argv[1])
for name, anchor, replacement in (
    ("app/dispatcher/default.go", '"context"', '"context"\n "github.com/xtls/xray-core/common/spectergate"'),
    ("app/dispatcher/default.go", "func (d *DefaultDispatcher) routedDispatch(ctx context.Context, link *transport.Link, destination net.Destination) {", "func (d *DefaultDispatcher) routedDispatch(ctx context.Context, link *transport.Link, destination net.Destination) {\n var admitted bool\n ctx, admitted = spectergate.Track(ctx, link)\n if !admitted { return }"),
    ("app/stats/command/command.go", '"context"', '"context"\n "github.com/xtls/xray-core/common/spectergate"'),
    ("app/stats/command/command.go", "func (s *service) Register(server *grpc.Server) {", "func (s *service) Register(server *grpc.Server) {\n spectergate.Register(server)"),
):
    path = root / name
    content = path.read_text(encoding="utf-8")
    if content.count(anchor) != 1:
        raise SystemExit(f"Unexpected upstream source: {name}")
    path.write_text(content.replace(anchor, replacement), encoding="utf-8")
target = root / "common/spectergate"
target.mkdir(parents=True, exist_ok=True)
for source in Path(__file__).parent.glob("*.go"):
    shutil.copyfile(source, target / source.name)
