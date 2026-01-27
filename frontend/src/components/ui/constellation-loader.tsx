import { useEffect, useRef } from 'react';

export default function ConstellationLoader() {
    const canvasRef = useRef<HTMLCanvasElement>(null);

    useEffect(() => {
        const canvas = canvasRef.current;
        if (!canvas) return;

        const ctx = canvas.getContext('2d');
        if (!ctx) return;

        const rootStyles = getComputedStyle(document.documentElement);
        const readVar = (name: string, fallback: string) => {
            const value = rootStyles.getPropertyValue(name).trim();
            return value || fallback;
        };
        const tokenColor = (name: string, alpha: number, fallback: string) =>
            `hsl(${readVar(name, fallback)} / ${alpha})`;

        const size = 800;
        canvas.width = size;
        canvas.height = size;

        const phi = (1 + Math.sqrt(5)) / 2;
        const vertices = [
            [-1, phi, 0], [1, phi, 0], [-1, -phi, 0], [1, -phi, 0],
            [0, -1, phi], [0, 1, phi], [0, -1, -phi], [0, 1, -phi],
            [phi, 0, -1], [phi, 0, 1], [-phi, 0, -1], [-phi, 0, 1]
        ];

        const faces = [
            [0, 11, 5], [0, 5, 1], [0, 1, 7], [0, 7, 10], [0, 10, 11],
            [1, 5, 9], [5, 11, 4], [11, 10, 2], [10, 7, 6], [7, 1, 8],
            [3, 9, 4], [3, 4, 2], [3, 2, 6], [3, 6, 8], [3, 8, 9],
            [4, 9, 5], [2, 4, 11], [6, 2, 10], [8, 6, 7], [9, 8, 1]
        ];

        const state = {
            rotX: 0,
            rotY: 0,
            velX: 0.006,
            velY: 0.01,
            dragging: false,
            lastX: 0,
            lastY: 0,
            lastTime: 0,
            glow: 1.0,
            targetGlow: 1.0
        };

        // Ensure initial velocity meets minimum speed
        const minSpeed = 0.01;
        const initialSpeed = Math.sqrt(state.velX * state.velX + state.velY * state.velY);
        if (initialSpeed < minSpeed) {
            const scale = minSpeed / initialSpeed;
            state.velX *= scale;
            state.velY *= scale;
        }

        const rotateX = (p: number[], a: number) => {
            const c = Math.cos(a), s = Math.sin(a);
            return [p[0], p[1] * c - p[2] * s, p[1] * s + p[2] * c];
        };

        const rotateY = (p: number[], a: number) => {
            const c = Math.cos(a), s = Math.sin(a);
            return [p[0] * c + p[2] * s, p[1], -p[0] * s + p[2] * c];
        };

        const project = (p: number[]) => {
            const z = p[2] + 6;
            const s = 4 / z * 120;
            return { x: p[0] * s + size / 2, y: p[1] * s + size / 2, z };
        };

        const onStart = (e: MouseEvent | TouchEvent) => {
            state.dragging = true;
            state.targetGlow = 1.8;
            const rect = canvas.getBoundingClientRect();
            const touch = (e as TouchEvent).touches?.[0];
            state.lastX = (touch ? touch.clientX : (e as MouseEvent).clientX) - rect.left;
            state.lastY = (touch ? touch.clientY : (e as MouseEvent).clientY) - rect.top;
            state.lastTime = Date.now();
        };

        const onMove = (e: MouseEvent | TouchEvent) => {
            if (!state.dragging) return;
            const rect = canvas.getBoundingClientRect();
            const touch = (e as TouchEvent).touches?.[0];
            const x = (touch ? touch.clientX : (e as MouseEvent).clientX) - rect.left;
            const y = (touch ? touch.clientY : (e as MouseEvent).clientY) - rect.top;
            const now = Date.now();
            const dt = Math.max(1, now - state.lastTime);
            const dx = x - state.lastX;
            const dy = y - state.lastY;
            state.rotY += dx * 0.01;
            state.rotX += dy * 0.01;
            state.velY = dx * 0.01 / dt * 16;
            state.velX = dy * 0.01 / dt * 16;
            state.lastX = x;
            state.lastY = y;
            state.lastTime = now;
        };

        const onEnd = () => {
            state.dragging = false;
            state.targetGlow = 1.0;
        };

        canvas.addEventListener('mousedown', onStart as any);
        canvas.addEventListener('mousemove', onMove as any);
        canvas.addEventListener('mouseup', onEnd);
        canvas.addEventListener('mouseleave', onEnd);
        canvas.addEventListener('touchstart', onStart as any);
        canvas.addEventListener('touchmove', onMove as any);
        canvas.addEventListener('touchend', onEnd);

        let id: number;

        const draw = () => {
            // Smooth glow transition
            state.glow += (state.targetGlow - state.glow) * 0.15;

            if (!state.dragging) {
                state.rotX += state.velX;
                state.rotY += state.velY;
                state.velX *= 0.995;
                state.velY *= 0.995;

                // Maintain minimum speed - never go below 0.01
                const minSpeed = 0.01;
                const speed = Math.sqrt(state.velX * state.velX + state.velY * state.velY);
                if (speed < minSpeed && speed > 0) {
                    const scale = minSpeed / speed;
                    state.velX *= scale;
                    state.velY *= scale;
                }
            }

            ctx.clearRect(0, 0, size, size);

            const pts = vertices.map(v => project(rotateY(rotateX(v, state.rotX), state.rotY)));

            const faceData = faces.map(f => {
                const [p1, p2, p3] = [pts[f[0]], pts[f[1]], pts[f[2]]];
                const z = (p1.z + p2.z + p3.z) / 3;
                // Standard back-face culling check
                const cross = (p2.x - p1.x) * (p3.y - p1.y) - (p2.y - p1.y) * (p3.x - p1.x);
                return { f, z, vis: cross > 0, pts: [p1, p2, p3] };
            }).filter(d => d.vis).sort((a, b) => b.z - a.z);

            faceData.forEach(({ pts: [p1, p2, p3], z }) => {
                const b = Math.max(0.4, Math.min(1, 1 / z)) * state.glow;
                ctx.beginPath();
                ctx.moveTo(p1.x, p1.y);
                ctx.lineTo(p2.x, p2.y);
                ctx.lineTo(p3.x, p3.y);
                ctx.closePath();

                // Amber fill (darker, semi-transparent)
                ctx.fillStyle = tokenColor('--amber-900', b * 0.6, '30 80% 10%');
                ctx.fill();

                // Amber stroke (bright)
                ctx.strokeStyle = tokenColor('--amber-500', b, '38 100% 50%');
                ctx.lineWidth = 3;
                ctx.shadowBlur = 25 * state.glow;
                ctx.shadowColor = tokenColor('--amber-500', b * 0.9, '38 100% 50%');
                ctx.stroke();
                ctx.shadowBlur = 0;
            });

            pts.forEach(p => {
                const b = Math.max(0.5, Math.min(1, 1 / p.z)) * state.glow;
                const sz = (5 + b * 4) * Math.sqrt(state.glow);
                const g = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, sz * 5);
                // Amber gradient particles
                g.addColorStop(0, tokenColor('--amber-200', b, '38 100% 85%'));
                g.addColorStop(0.3, tokenColor('--amber-500', b * 0.7, '38 100% 50%'));
                g.addColorStop(0.6, tokenColor('--amber-600', b * 0.4, '32 100% 45%'));
                g.addColorStop(1, tokenColor('--amber-700', 0, '30 100% 40%'));

                ctx.fillStyle = g;
                ctx.fillRect(p.x - sz * 5, p.y - sz * 5, sz * 10, sz * 10);

                ctx.fillStyle = tokenColor('--amber-100', b, '38 100% 92%');
                ctx.beginPath();
                ctx.arc(p.x, p.y, sz, 0, Math.PI * 2);
                ctx.fill();
            });

            id = requestAnimationFrame(draw);
        };

        id = requestAnimationFrame(draw);

        return () => {
            cancelAnimationFrame(id);
            canvas.removeEventListener('mousedown', onStart as any);
            canvas.removeEventListener('mousemove', onMove as any);
            canvas.removeEventListener('mouseup', onEnd);
            canvas.removeEventListener('mouseleave', onEnd);
            canvas.removeEventListener('touchstart', onStart as any);
            canvas.removeEventListener('touchmove', onMove as any);
            canvas.removeEventListener('touchend', onEnd);
        };
    }, []);

    return (
        <div className="w-full h-full flex justify-center items-center">
            <canvas
                ref={canvasRef}
                style={{
                    width: '60vmin',
                    height: '60vmin',
                    maxWidth: '400px',
                    maxHeight: '400px',
                    display: 'block',
                    cursor: 'grab'
                }}
            />
        </div>
    );
}
