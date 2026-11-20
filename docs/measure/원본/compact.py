# compact.py [GiB] — 익명 mmap을 MADV_HUGEPAGE로 잡아 4 KiB마다 건드린 뒤 놓는다. MemAvailable이 1.5 GiB 아래면 멈춘다.
import mmap, sys

def avail_kb():
    for ln in open('/proc/meminfo'):
        if ln.startswith('MemAvailable:'):
            return int(ln.split()[1])
    return 0

def o7():
    for ln in open('/proc/buddyinfo'):
        if 'Normal' in ln:
            return sum(int(x) for x in ln.split()[4:][7:])
    return -1

gib = int(sys.argv[1]) if len(sys.argv) > 1 else 4
size = gib << 30
print('before o7+', o7(), 'avail_gib', round(avail_kb() / 1048576, 2))
m = mmap.mmap(-1, size, flags=mmap.MAP_PRIVATE | mmap.MAP_ANONYMOUS)
m.madvise(mmap.MADV_HUGEPAGE)
step = 4096
chunk = 256 << 20
done = 0
stopped = False
while done < size:
    if avail_kb() < 1572864:
        stopped = True
        break
    end = min(done + chunk, size)
    for off in range(done, end, step):
        m[off] = 1
    done = end
print('touched_gib', round(done / (1 << 30), 2), 'stopped_early', stopped)
m.close()
print('after o7+', o7(), 'avail_gib', round(avail_kb() / 1048576, 2))
