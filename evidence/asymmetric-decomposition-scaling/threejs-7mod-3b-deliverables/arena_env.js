import * as THREE from 'https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js';

export function createArenaEnv(mountEl) {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x060918);

  const camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.1, 500);
  camera.position.set(0, 12, 16);
  camera.lookAt(0, 0, 0);

  const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
  renderer.setSize(window.innerWidth, window.innerHeight);
  mountEl.appendChild(renderer.domElement);

  const ambientLight = new THREE.AmbientLight(0x94a3b8, 1.8);
  scene.add(ambientLight);

  const directionalLight = new THREE.DirectionalLight(0xffffff, 2.2);
  directionalLight.position.set(8, 18, 10);
  scene.add(directionalLight);

  const gridHelper = new THREE.GridHelper(24, 24, 0x38bdf8, 0x1e293b);
  scene.add(gridHelper);

  const coords = new Float32Array(900);
  for (let k = 0; k < 900; k++) {
    coords[k] = (Math.random() - 0.5) * 70;
  }

  const starGeo = new THREE.BufferGeometry();
  starGeo.setAttribute('position', new THREE.BufferAttribute(coords, 3));

  const starMaterial = new THREE.PointsMaterial({ color: 0xe2e8f0, size: 0.22 });

  const stars = new THREE.Points(starGeo, starMaterial);
  scene.add(stars);

  return { scene, camera, renderer };
}
