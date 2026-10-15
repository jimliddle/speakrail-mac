/* Local Three.js face rig. Phoneme weights deform authored mouth shapes;
 * teeth, tongue and the wire overlay share those same weights.
 */
(() => {
  "use strict";
  const baseURL = document.currentScript.src;
  const assetURL = new URL("assets/mesh-face/mpfb.glb", baseURL);
  const POSES = [
    "Rest", "M / B / P", "F / V", "TH", "T / D", "K / G", "CH / SH / J", "S / Z",
    "N / L", "R", "A / AH", "E / EH", "I / EE", "O / OH", "U / OO", "Blink",
    "Listening", "Thinking", "Curious", "Smiling", "Laughing", "Surprised", "Concerned", "Reassuring",
  ];
  const VISEMES = [null, "PP", "FF", "TH", "DD", "kk", "CH", "SS", "nn", "RR", "aa", "E", "I", "O", "U"];
  const GAIN = [0, 1, .85, .7, .8, .7, .8, .7, .7, .8, .65, .65, .65, .8, .85];
  const STATE_POSE = { idle: 0, listening: 16, thinking: 17, error: 22, smiling: 19, curious: 18, reassuring: 23 };

  class MeshAvatar {
    static poses = POSES;
    constructor(onError) {
      this.onError = onError;
      this.ready = false;
      this.loading = null;
      this.pose = 0;
      this.targets = [];
      this.nextBlink = 4000;
      this.blinkAt = null;
      this.reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
    }

    resetMouth() {
      this.pose = 0;
      for (const mesh of this.targets) mesh.morphTargetInfluences.fill(0);
    }

    load() {
      if (this.loading) return this.loading;
      this.loading = this.prepare().then(() => { this.ready = true; return true; }).catch(error => {
        console.warn("Face rig unavailable:", error);
        this.dispose();
        this.loading = null;
        this.ready = false;
        this.onError?.();
        return false;
      });
      return this.loading;
    }

    async prepare() {
      this.dispose();
      const THREE = await import("three");
      const { GLTFLoader } = await import(new URL("vendor/three/loaders/GLTFLoader.js", baseURL));
      const gltf = await new GLTFLoader().loadAsync(assetURL.href);
      this.THREE = THREE;
      this.scene = new THREE.Scene();
      this.scene.background = new THREE.Color(0x050907);
      this.model = gltf.scene;
      this.scene.add(this.model);
      this.camera = new THREE.OrthographicCamera(-.2, .2, .2, -.2, .01, 10);
      this.camera.position.set(0, 1.635, 1.5);
      this.camera.lookAt(0, 1.635, 0);
      this.renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
      this.renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 1.5));
      this.renderer.localClippingEnabled = true;
      this.renderer.domElement.addEventListener("webglcontextlost", event => {
        event.preventDefault();
        this.ready = false;
        this.loading = null;
        this.onError?.();
      });
      this.scene.add(new THREE.HemisphereLight(0xa6ffcd, 0x06140e, 2));
      const key = new THREE.DirectionalLight(0xd5ffe8, 3);
      key.position.set(-1, 2, 3);
      this.scene.add(key);
      const rim = new THREE.DirectionalLight(0x50ffb0, 2);
      rim.position.set(1, 1.8, -.5);
      this.scene.add(rim);
      // Hide the unused body below the neck; camera fitting includes the hair.
      const clippingPlanes = [new THREE.Plane(new THREE.Vector3(0, 1, 0), -1.44)];
      const meshes = [];
      this.model.traverse(node => { if (node.isMesh) meshes.push(node); });
      this.targets = [];
      for (const mesh of meshes) {
        if (mesh.morphTargetInfluences) this.targets.push(mesh);
        mesh.frustumCulled = false;
        const name = mesh.name.toLowerCase();
        if (name.includes("casualsuit")) { mesh.visible = false; continue; }
        const eyes = name.includes("high-poly"), hair = name.includes("ponytail");
        const detail = name.includes("eyebrow") || name.includes("eyelash");
        const teeth = name.includes("teeth"), tongue = name.includes("tongue");
        if (eyes || detail || hair) {
          mesh.material = mesh.material.clone();
          mesh.material.color.set(eyes ? 0xb1ebca : hair ? 0x26774c : 0x215339);
          mesh.material.roughness = .8;
          mesh.material.clippingPlanes = clippingPlanes;
        } else {
          mesh.material = new THREE.MeshStandardMaterial({
            color: teeth ? 0x91b99c : tongue ? 0x193c29 : 0x125336,
            roughness: .64, metalness: .1, clippingPlanes,
            polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1,
          });
        }
        if (!eyes && !detail && !teeth && !tongue && !hair) {
          const wire = mesh.clone(false);
          wire.name = mesh.name + "_wire";
          wire.material = new THREE.MeshBasicMaterial({ color: 0x45be7e, wireframe: true,
            transparent: true, opacity: .085, depthWrite: false, clippingPlanes });
          wire.morphTargetInfluences = mesh.morphTargetInfluences;
          wire.frustumCulled = false;
          mesh.parent.add(wire);
        }
      }
      this.head = this.model.getObjectByName("Head");
      this.headRest = this.head?.quaternion.clone();
      if (!this.targets.some(mesh => mesh.morphTargetDictionary?.viseme_aa !== undefined)) {
        throw new Error("Face asset has no speech shapes");
      }
      this.model.updateMatrixWorld(true);
    }

    setShape(name, value) {
      for (const mesh of this.targets) {
        const index = mesh.morphTargetDictionary[name];
        if (index !== undefined) mesh.morphTargetInfluences[index] = Math.max(0, Math.min(1, value));
      }
    }

    draw(ctx, t, w, h, { state = "idle", mouthWeights = null, previewPose = null } = {}) {
      if (!this.ready) return false;
      this.resetMouth();
      const speaking = state === "speaking" && mouthWeights && previewPose == null;
      this.pose = previewPose ?? (speaking ? mouthWeights.indexOf(Math.max(...mouthWeights)) : STATE_POSE[state] ?? 0);
      if (speaking) {
        VISEMES.forEach((name, i) => { if (name) this.setShape("viseme_" + name, mouthWeights[i] * GAIN[i]); });
      } else if (this.pose > 0 && this.pose < 15) {
        this.setShape("viseme_" + VISEMES[this.pose], GAIN[this.pose]);
      }
      const shapes = {
        16: { browInnerUp: .12 }, 17: { browDownLeft: .18, eyeSquintRight: .12 },
        18: { browOuterUpLeft: .45, browInnerUp: .2 },
        19: { mouthSmileLeft: .55, mouthSmileRight: .55, cheekSquintLeft: .2, cheekSquintRight: .2 },
        20: { mouthSmileLeft: .6, mouthSmileRight: .6, jawOpen: .35 },
        21: { browInnerUp: .65, eyeWideLeft: .4, eyeWideRight: .4, jawOpen: .3 },
        22: { browInnerUp: .4, mouthFrownLeft: .18, mouthFrownRight: .18 },
        23: { mouthSmileLeft: .25, mouthSmileRight: .25, browInnerUp: .1 },
      };
      for (const [name, weight] of Object.entries(shapes[this.pose] || {})) this.setShape(name, weight);
      let blink = this.pose === 15 ? 1 : 0;
      if (!this.reducedMotion.matches && previewPose == null) {
        if (this.blinkAt == null && t >= this.nextBlink) this.blinkAt = t;
        if (this.blinkAt != null) {
          const progress = (t - this.blinkAt) / 180;
          if (progress >= 1) { this.blinkAt = null; this.nextBlink = t + 4000 + Math.random() * 2000; }
          else blink = Math.sin(progress * Math.PI);
        }
      }
      this.setShape("eyeBlinkLeft", blink); this.setShape("eyeBlinkRight", blink);
      if (this.head) {
        this.head.quaternion.copy(this.headRest);
        if (!this.reducedMotion.matches && previewPose == null) {
          this.head.rotateY(Math.sin(t * .00036) * .025);
          this.head.rotateX(Math.sin(t * .00053) * .012);
        }
      }
      const height = Math.max(80, Math.min(700, h - 185));
      const width = Math.min(w, 900);
      if (width !== this.renderWidth || height !== this.renderHeight) {
        this.renderer.setSize(width, height, false);
        const halfHeight = Math.max(.205, .15 * height / width);
        this.camera.top = halfHeight; this.camera.bottom = -halfHeight;
        this.camera.left = -halfHeight * width / height; this.camera.right = -this.camera.left;
        this.camera.updateProjectionMatrix();
        this.renderWidth = width; this.renderHeight = height;
      }
      this.renderer.render(this.scene, this.camera);
      this.bounds = { x: (w - width) / 2, y: 20, width, height };
      ctx.drawImage(this.renderer.domElement, this.bounds.x, this.bounds.y, width, height);
      return true;
    }

    dispose() {
      const geometries = new Set(), materials = new Set(), textures = new Set(), skeletons = new Set();
      this.scene?.traverse(node => {
        if (node.geometry) geometries.add(node.geometry);
        if (node.skeleton) skeletons.add(node.skeleton);
        for (const material of [node.material].flat().filter(Boolean)) {
          materials.add(material);
          for (const value of Object.values(material)) if (value?.isTexture) textures.add(value);
        }
      });
      for (const resource of [...geometries, ...materials, ...textures, ...skeletons]) resource.dispose();
      this.renderer?.dispose();
      this.scene = null;
      this.renderer = null;
      this.targets = [];
      this.renderWidth = this.renderHeight = null;
    }
  }
  window.MeshAvatar = MeshAvatar;
})();
