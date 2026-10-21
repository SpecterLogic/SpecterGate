// Package spectergate provides local, authenticated-flow session control.
// The service is exposed only through Xray's existing loopback API listener.
package spectergate

import (
	"context"
	"net/netip"
	"sort"
	"sync"
	"time"

	"github.com/xtls/xray-core/common"
	"github.com/xtls/xray-core/common/session"
	"github.com/xtls/xray-core/transport"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/structpb"
)

type flow struct {
	user, ip string
	started  time.Time
	close    func()
}
type registry struct {
	sync.Mutex
	ready  bool
	next   uint64
	flows  map[uint64]flow
	limits map[string]int
	blocks map[string]time.Time
}

func newRegistry() *registry {
	return &registry{flows: map[uint64]flow{}, limits: map[string]int{}, blocks: map[string]time.Time{}}
}

var active = newRegistry()

func key(user, ip string) string { return user + "\x00" + ip }

func (r *registry) admit(user, ip string, close func()) (func(), bool) {
	r.Lock()
	defer r.Unlock()
	if !r.ready {
		return nil, false
	}
	if time.Now().Before(r.blocks[key(user, ip)]) {
		return nil, false
	}
	ips := map[string]bool{}
	for _, f := range r.flows {
		if f.user == user {
			ips[f.ip] = true
		}
	}
	if limit := r.limits[user]; limit > 0 && !ips[ip] && len(ips) >= limit {
		return nil, false
	}
	r.next++
	id := r.next
	r.flows[id] = flow{user, ip, time.Now(), close}
	return func() { r.Lock(); delete(r.flows, id); r.Unlock() }, true
}

// Track is called on logical dispatch links, including multiplexed transports.
// Cancelling one dispatch context does not cancel its parent connection.
func Track(ctx context.Context, link *transport.Link) (context.Context, bool) {
	inbound := session.InboundFromContext(ctx)
	if inbound == nil || inbound.User == nil || inbound.User.Email == "" {
		return ctx, true
	}
	child, cancel := context.WithCancel(ctx)
	close := func() { cancel(); common.Interrupt(link.Reader); common.Interrupt(link.Writer) }
	release, ok := active.admit(inbound.User.Email, inbound.Source.Address.String(), close)
	if !ok {
		close()
		return child, false
	}
	context.AfterFunc(child, release)
	return child, true
}

func (r *registry) configure(limits map[string]int, blocks map[string]time.Time) int {
	r.Lock()
	r.limits, r.blocks = limits, blocks
	r.ready = true
	// Preserve oldest admitted IPs when lowering a user's limit.
	ids := make([]uint64, 0, len(r.flows))
	for id := range r.flows {
		ids = append(ids, id)
	}
	sort.Slice(ids, func(i, j int) bool { return ids[i] < ids[j] })
	accepted := map[string]map[string]bool{}
	var closing []func()
	for _, id := range ids {
		f := r.flows[id]
		if accepted[f.user] == nil {
			accepted[f.user] = map[string]bool{}
		}
		ips := accepted[f.user]
		blocked := time.Now().Before(blocks[key(f.user, f.ip)])
		limit := limits[f.user]
		if blocked || (limit > 0 && !ips[f.ip] && len(ips) >= limit) {
			delete(r.flows, id)
			closing = append(closing, f.close)
		} else {
			ips[f.ip] = true
		}
	}
	r.Unlock()
	for _, close := range closing {
		close()
	}
	return len(closing)
}

type service interface{}
type controller struct{}

func response(values map[string]interface{}) (*structpb.Struct, error) {
	return structpb.NewStruct(values)
}
func execute(ctx context.Context, method string, request *structpb.Struct) (*structpb.Struct, error) {
	if method == "Snapshot" {
		active.Lock()
		rows := []interface{}{}
		for _, f := range active.flows {
			rows = append(rows, map[string]interface{}{"user": f.user, "ip": f.ip, "since": float64(f.started.Unix())})
		}
		active.Unlock()
		return response(map[string]interface{}{"protocol_version": 1, "flows": rows})
	}
	values := request.AsMap()
	limits := map[string]int{}
	rawLimits, ok := values["limits"].(map[string]interface{})
	if !ok || len(rawLimits) > 100000 {
		return nil, status.Error(codes.InvalidArgument, "invalid limits")
	}
	for user, v := range rawLimits {
		n, ok := v.(float64)
		if !ok || user == "" || len(user) > 256 || n < 0 || n > 100000 || n != float64(int(n)) {
			return nil, status.Error(codes.InvalidArgument, "invalid limit")
		}
		limits[user] = int(n)
	}
	blocks := map[string]time.Time{}
	rawBlocks, ok := values["blocks"].([]interface{})
	if !ok || len(rawBlocks) > 100000 {
		return nil, status.Error(codes.InvalidArgument, "invalid blocks")
	}
	for _, raw := range rawBlocks {
		row, ok := raw.(map[string]interface{})
		if !ok {
			return nil, status.Error(codes.InvalidArgument, "invalid block")
		}
		user, _ := row["user"].(string)
		ip, _ := row["ip"].(string)
		until, ok := row["until"].(float64)
		addr, err := netip.ParseAddr(ip)
		if user == "" || len(user) > 256 || err != nil || !ok || until < 0 || until > float64(time.Now().Add(24*time.Hour).Unix()) {
			return nil, status.Error(codes.InvalidArgument, "invalid block")
		}
		blocks[key(user, addr.Unmap().String())] = time.Unix(int64(until), 0)
	}
	count := active.configure(limits, blocks)
	return response(map[string]interface{}{"protocol_version": 1, "closed": count})
}
func handler(method string) grpc.MethodDesc {
	return grpc.MethodDesc{MethodName: method, Handler: func(srv interface{}, ctx context.Context, decode func(interface{}) error, interceptor grpc.UnaryServerInterceptor) (interface{}, error) {
		request := new(structpb.Struct)
		if err := decode(request); err != nil {
			return nil, err
		}
		invoke := func(ctx context.Context, req interface{}) (interface{}, error) {
			return execute(ctx, method, req.(*structpb.Struct))
		}
		if interceptor != nil {
			return interceptor(ctx, request, &grpc.UnaryServerInfo{Server: srv, FullMethod: "/spectergate.control.SessionService/" + method}, invoke)
		}
		return invoke(ctx, request)
	}}
}
func Register(server *grpc.Server) {
	server.RegisterService(&grpc.ServiceDesc{ServiceName: "spectergate.control.SessionService", HandlerType: (*service)(nil), Methods: []grpc.MethodDesc{handler("Snapshot"), handler("Configure")}}, &controller{})
}
