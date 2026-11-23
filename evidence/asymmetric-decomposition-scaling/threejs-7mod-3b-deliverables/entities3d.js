import * as THREE from 'https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js';

export function createEntities(scene) {
    const shipGroup = new THREE.Group();
    const shipMesh = new THREE.Mesh(new THREE.ConeGeometry(0.6, 1.8, 16), new THREE.MeshStandardMaterial({color: 0x00f5ff, emissive: 0x0284c7, emissiveIntensity: 0.9}));
    shipMesh.rotation.x = Math.PI / 2;
    shipGroup.add(shipMesh);

    const prismMeshes = [];
    for (let i = 0; i < 8; i++) {
        const prismMesh = new THREE.Mesh(new THREE.OctahedronGeometry(0.55, 0), new THREE.MeshStandardMaterial({color: i % 2 === 0 ? 0xfbbf24 : 0xe879f9, emissive: i % 2 === 0 ? 0xd97706 : 0xc026d3, emissiveIntensity: 0.8}));
        prismMeshes.push(prismMesh);
        shipGroup.add(prismMesh);
    }

    shipGroup.position.set(0, 0.6, 0);
    scene.add(shipGroup);

    return {shipGroup, prismMeshes};
}

export function syncEntities(entities, state, elapsedSec) {
    entities.shipGroup.position.set(state.ship.x, 0.6, state.ship.z);
    for (let k = 0; k < 8; k++) {
        const targetPrismMesh = entities.prismMeshes[k];
        const targetPrism = state.prisms[k];
        targetPrismMesh.position.set(targetPrism.x, 0.6, targetPrism.z);
    }
}
