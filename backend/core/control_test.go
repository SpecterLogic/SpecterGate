package spectergate

import (
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func TestIsolationAndLimits(t *testing.T) {
	r := newRegistry()
	var first, second, other atomic.Int32
	if _, ok := r.admit("a", "192.0.2.1", func() {}); ok {
		t.Fatal("admitted before policy load")
	}
	r.configure(map[string]int{}, map[string]time.Time{})
	r.admit("a", "192.0.2.1", func() { first.Add(1) })
	r.admit("a", "192.0.2.2", func() { second.Add(1) })
	release, _ := r.admit("b", "192.0.2.2", func() { other.Add(1) })
	if r.configure(map[string]int{"a": 1}, map[string]time.Time{}) != 1 || second.Load() != 1 || first.Load() != 0 || other.Load() != 0 {
		t.Fatal("limit affected wrong flows")
	}
	if _, ok := r.admit("a", "192.0.2.3", func() {}); ok {
		t.Fatal("limit bypassed")
	}
	if _, ok := r.admit("a", "192.0.2.1", func() {}); !ok {
		t.Fatal("same IP rejected")
	}
	r.configure(map[string]int{}, map[string]time.Time{key("a", "192.0.2.1"): time.Now().Add(time.Minute)})
	if first.Load() != 1 || other.Load() != 0 {
		t.Fatal("block escaped user scope")
	}
	if _, ok := r.admit("a", "192.0.2.1", func() {}); ok {
		t.Fatal("block bypassed")
	}
	release()
	release()
}

func TestConcurrentAdmissionAndRelease(t *testing.T) {
	r := newRegistry()
	r.configure(map[string]int{"a": 1}, map[string]time.Time{})
	var wg sync.WaitGroup
	var count atomic.Int32
	releases := make(chan func(), 100)
	for i := 0; i < 100; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			ip := "192.0.2.1"
			if i%2 == 0 {
				ip = "192.0.2.2"
			}
			release, ok := r.admit("a", ip, func() {})
			if ok {
				count.Add(1)
				releases <- release
			}
		}(i)
	}
	wg.Wait()
	close(releases)
	r.Lock()
	ips := map[string]bool{}
	for _, f := range r.flows {
		ips[f.ip] = true
	}
	r.Unlock()
	if len(ips) != 1 || count.Load() == 0 {
		t.Fatal("non-atomic admission")
	}
	for release := range releases {
		release()
	}
	if len(r.flows) != 0 {
		t.Fatal("slots leaked")
	}
	r.configure(map[string]int{}, map[string]time.Time{key("a", "192.0.2.1"): time.Now().Add(-time.Second)})
	if _, ok := r.admit("a", "192.0.2.1", func() {}); !ok {
		t.Fatal("expired block retained")
	}
}
